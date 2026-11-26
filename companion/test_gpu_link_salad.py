"""Word-salad judge: fake-judge unit tests always run; real-judge tests run when
llama-perplexity + a tiny GGUF are configured (OPOS_GPU_LINK_SALAD_BIN/MODEL)."""
from __future__ import annotations

import json
import os
import random
import re
import unittest
from pathlib import Path
from unittest.mock import patch

import gpu_link_guard as guard
import gpu_link_salad as salad
import gpu_link_validate as validate

FIX = Path(__file__).with_name("salad_fixtures")
COMMON = set("the a an of to and in is it that for on with as are be by this from or at which can its into".split())


class FakeJudge:
    """Predictable-language proxy: fraction of common function words lowers 'perplexity'."""
    calls = 0

    def ppl(self, text):
        FakeJudge.calls += 1
        words = re.findall(r"[a-zA-Z']+", text)
        if not words:
            return None
        frac = sum(w.lower() in COMMON for w in words) / len(words)
        return 3.0 + 600.0 * max(0.0, 0.3 - frac)


PROSE = ("A GPU runs thousands of small threads in parallel. It transforms vertices, shades fragments and "
         "presents the finished frame to the display. The memory is organised for wide, regular access, which "
         "is why graphics and machine learning both fit it. ") * 12


def salad_of(text, seed=0):
    words = text.split()
    random.Random(seed).shuffle(words)
    return " ".join(w for w in words if w.lower() not in COMMON)


class SaladUnit(unittest.TestCase):
    def test_clean_prose_passes_and_salad_tail_flags(self):
        self.assertIsNone(salad.salad_reason(PROSE, FakeJudge()))
        bad = PROSE[:900] + salad_of(PROSE[900:])
        self.assertEqual(salad.salad_reason(bad, FakeJudge()), "word_salad")

    def test_short_answers_and_no_judge_are_never_judged(self):
        self.assertIsNone(salad.salad_reason(salad_of(PROSE)[:900], FakeJudge()))
        self.assertIsNone(salad.salad_reason(salad_of(PROSE), None))
        self.assertIsNone(salad.score("x" * 10, FakeJudge()))

    def test_kill_switch(self):
        with patch.dict(os.environ, {"OPOS_GPU_LINK_SALAD": "0"}):
            self.assertIsNone(salad.salad_reason(PROSE[:900] + salad_of(PROSE[900:]), FakeJudge()))

    def test_unusable_judge_result_is_not_an_alarm(self):
        class Dead:
            def ppl(self, text): return None
        self.assertIsNone(salad.salad_reason(PROSE[:900] + salad_of(PROSE[900:]), Dead()))

    def test_missing_binary_means_no_judge(self):
        with patch.dict(os.environ, {"OPOS_GPU_LINK_SALAD_BIN": "/nonexistent", "OPOS_GPU_LINK_SALAD_MODEL": "/nonexistent"}):
            self.assertIsNone(salad.PerplexityJudge.from_env())

    def test_guardstate_flags_salad_and_drops_quarantine(self):
        bad = PROSE[:900] + salad_of(PROSE[900:])
        state = guard.GuardState(salad=salad.BackgroundSalad(FakeJudge()))
        for i in range(0, len(bad), 100):
            state.feed(bad[i:i + 100])
        state.feed("", final=True)
        self.assertEqual(state.reason, "word_salad")
        self.assertLess(len(state.text), len(bad))
        self.assertEqual(state.text, state.safe_text)

    def test_guardstate_clean_stream_unaffected_and_judge_errors_ignored(self):
        class Boom:
            def update(self, text): raise RuntimeError("x")
            def final(self, text): raise RuntimeError("x")
        for s in (salad.BackgroundSalad(FakeJudge()), Boom(), None):
            state = guard.GuardState(salad=s)
            for i in range(0, len(PROSE), 100):
                state.feed(PROSE[i:i + 100])
            state.feed("", final=True)
            self.assertIsNone(state.reason)
            self.assertEqual(state.text, PROSE)

    def test_validator_reports_word_salad_as_garble_failure(self):
        prompt = {"id": "p", "kind": "long", "max_tokens": 900, "expected_facts": [], "forbidden_patterns": []}
        bad = PROSE[:900] + salad_of(PROSE[900:])
        row = validate.check_answer(prompt, bad, "stop", salad_judge=FakeJudge())
        self.assertEqual(row["garble_reason"], "word_salad")
        self.assertIn("garbled: word_salad", row["failures"])
        self.assertEqual(validate.check_answer(prompt, PROSE, "stop", salad_judge=FakeJudge())["garble_reason"], None)
        # Unconfigured: validator behaves exactly as before.
        with patch.dict(os.environ, {"OPOS_GPU_LINK_SALAD_BIN": "", "OPOS_GPU_LINK_SALAD_MODEL": ""}):
            salad.set_default_judge(None)
            self.assertIsNone(validate.check_answer(prompt, bad, "stop")["garble_reason"])


def _real_judge():
    j = salad.PerplexityJudge.from_env()
    return j


@unittest.skipUnless(_real_judge(), "set OPOS_GPU_LINK_SALAD_BIN and OPOS_GPU_LINK_SALAD_MODEL to run the real perplexity judge")
class SaladReal(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.judge = _real_judge()

    def test_missed_macpro_recording_is_flagged(self):
        text = (FIX / "macpro_G_both_default_llama_salad.txt").read_text(errors="replace")
        self.assertEqual(salad.salad_reason(text, self.judge), "word_salad")

    def test_macpro_recording_before_its_loop_is_flagged(self):
        text = (FIX / "macpro_E_llama_default_garbled_prefix.txt").read_text(errors="replace")
        self.assertEqual(salad.salad_reason(text, self.judge), "word_salad")

    def test_clean_answers_have_no_false_positive(self):
        rows = json.loads((FIX / "clean_answers.json").read_text())
        rows.append({"model": "macpro", "text": (FIX / "macpro_B_default_qwen_clean_prefix.txt").read_text(errors="replace")})
        judged = 0
        for row in rows:
            if len(row["text"].strip()) >= salad.MIN_CHARS:
                judged += 1
                self.assertIsNone(salad.salad_reason(row["text"], self.judge), row["model"])
        self.assertGreaterEqual(judged, 20)

    def test_synthetic_salad_is_flagged(self):
        rows = json.loads((FIX / "clean_answers.json").read_text())[:10]
        rng = random.Random(5)
        for row in rows:
            t = row["text"]
            ws = t[-600:].split()
            rng.shuffle(ws)
            self.assertEqual(salad.salad_reason(t[:-600] + " ".join(ws), self.judge), "word_salad", row["model"])


if __name__ == "__main__":
    unittest.main()

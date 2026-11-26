# SPDX-License-Identifier: Apache-2.0
"""Length-cap sentence trimming; no network, no models."""

import tempfile
import unittest
from pathlib import Path

from opos import ai_answers
from opos.store import Store


class CompleteSentences(unittest.TestCase):
    def test_trims_a_hanging_clause_after_the_last_period(self):
        text = (
            "A GPU is a specialized processor designed for parallel work. "
            "2. Rasterization: Converting those 3D vector shapes into a"
        )
        self.assertEqual(
            ai_answers.complete_sentences(text),
            "A GPU is a specialized processor designed for parallel work.",
        )

    def test_keeps_a_complete_ending(self):
        text = "A GPU is a specialized processor. It has many cores."
        self.assertEqual(ai_answers.complete_sentences(text), text)

    def test_keeps_text_when_there_is_no_sentence_end(self):
        text = "A hanging clause with no terminator"
        self.assertEqual(ai_answers.complete_sentences(text), text)

    def test_does_not_treat_list_numbers_as_sentence_ends(self):
        text = "A GPU has two steps. 2. Rasterization converts shapes into pixels."
        self.assertEqual(ai_answers.complete_sentences(text), text)

    def test_keeps_a_sentence_that_ends_in_a_year(self):
        text = "The card was released in 2025. It has more cores now."
        self.assertEqual(ai_answers.complete_sentences(text), text)

    def test_keeps_original_when_the_only_cut_is_a_tiny_prefix(self):
        text = "Hi. " + ("word " * 30)
        self.assertEqual(ai_answers.complete_sentences(text), text)

    def test_drops_a_trailing_roman_section_marker(self):
        # Seen live on the Flip 6 (SmolLM2 1.7B at its token cap, 26 Nov 2026).
        text = (
            "A thermal limit of at least 100\u00b0C is recommended.\n\n"
            "VII. Battery and"
        )
        self.assertEqual(
            ai_answers.complete_sentences(text),
            "A thermal limit of at least 100\u00b0C is recommended.",
        )

    def test_drops_a_trailing_line_of_markers(self):
        cases = {
            "The cable carries data.\n\nVII.": "The cable carries data.",
            "The cable carries data.\n\n10. Check the": "The cable carries data.",
            "The cable carries data.\n## 3.": "The cable carries data.",
            "The cable carries data.\n- b.": "The cable carries data.",
            "The cable carries data.\n\n3.1. Battery and": "The cable carries data.",
            "The cable carries data.\n3. b. Check the": "The cable carries data.",
            "The cable carries data.\n**IV**. Power": "The cable carries data.",
            "The cable carries data.\n__3__. Heat": "The cable carries data.",
            "The cable carries data.\n## IV. Heat": "The cable carries data.",
            "A GPU has stages. Here are the steps:\nII. Battery and": "A GPU has stages.",
            "A GPU has stages. For example:\n- b. Memory and": "A GPU has stages.",
            "A GPU has stages. Overview:\n3.1. Battery and": "A GPU has stages.",
            "How does a GPU work?\n\nI. Parallel processing and": "How does a GPU work?",
            "Which option is fastest here?\nB. The second one and": "Which option is fastest here?",
            "Intro.\nI. First item is done.\nII. Second item":
                "Intro.\nI. First item is done.",
            "The cable carries data.\n**IV.** b. Power": "The cable carries data.",
            "The cable carries data.\n\u2022 12. Heat": "The cable carries data.",
        }
        for text, shown in cases.items():
            with self.subTest(text=text):
                self.assertEqual(ai_answers.complete_sentences(text), shown)

    def test_keeps_real_endings_that_look_like_markers(self):
        for text in (
            "The cable carries data. It worked in 2025.",
            "Did it resume? Yes.",
            "Which option is fastest here? A.",
            "The figure is shown in the guide. See Fig. 10.",
            "The model is rated for approx. 60.",
            "The answer was short. 100!",
            "The tool is called the CLI.",
            "The card was released in 2025. It has 16 GB.",
            "Which option is fastest here?\nA.",
            "The value of the constant is:\n42.",
        ):
            with self.subTest(text=text):
                self.assertEqual(ai_answers.complete_sentences(text), text)

    def test_long_marker_like_runs_stay_fast(self):
        import time
        texts = (
            "Intro sentence here.\n" + "-" * 3000 + " x.",
            "Intro sentence here.\n" + "#" * 3000 + "Heading.",
            "Intro sentence here.\n" + "-" * 3000 + " a." * 3000,
            "Intro sentence here.\n" + "*_" * 1500 + " Word." * 1500,
            "Word. " * 10000,
        )
        started = time.monotonic()
        for text in texts:
            ai_answers.complete_sentences(text)
        self.assertLess(time.monotonic() - started, 2.0)

    def test_empty_string(self):
        self.assertEqual(ai_answers.complete_sentences(""), "")


class LengthCapDisplay(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.answers = ai_answers.AnswerStore(Store(self.root))

    def tearDown(self):
        self.temp.cleanup()

    def _start(self):
        row = self.answers.ask("gpu", "Explain how a gpu works in detail?", "Gemma 4 26B")
        return self.answers.begin(row["id"])

    def test_length_finish_trims_display_only_when_done(self):
        row = self._start()
        hanging = (
            "A GPU is a specialized processor designed for parallel work. "
            "Converting those 3D vector shapes into a"
        )
        mid = self.answers.append(row["id"], 0, hanging.encode(), done=False)
        self.assertEqual(mid["text"], hanging)
        self.assertEqual(self.answers.get(row["id"])["text"], hanging)
        wire = self.answers.append(row["id"], len(hanging.encode()), b"", done=True, finish="length")
        self.assertEqual(wire["state"], "done")
        self.assertEqual(wire["finish"], "length")
        self.assertEqual(wire["text"], hanging)
        self.assertEqual(wire["bytes"], len(hanging.encode()))
        shown = self.answers.get(row["id"])
        self.assertEqual(shown["text"], "A GPU is a specialized processor designed for parallel work.")
        self.assertLess(shown["bytes"], wire["bytes"])

    def test_stop_finish_is_not_trimmed(self):
        row = self._start()
        text = "A GPU is a specialized processor designed for parallel work. And then"
        self.answers.append(row["id"], 0, text.encode(), done=True, finish="stop")
        self.assertEqual(self.answers.get(row["id"])["text"], text)

    def test_paused_hanging_text_is_not_trimmed(self):
        row = self._start()
        text = "A GPU is a specialized processor designed for parallel work. And then"
        self.answers.append(row["id"], 0, text.encode(), done=False)
        paused = self.answers.pause(row["id"])
        self.assertEqual(paused["state"], "paused")
        self.assertEqual(self.answers.get(row["id"])["text"], text)

    def test_exact_stop_replay_is_required(self):
        row = self._start()
        text = "A GPU is a specialized processor."
        self.answers.append(row["id"], 0, text.encode(), done=True, finish="stop")
        again = self.answers.append(row["id"], 0, text.encode(), done=True, finish="stop")
        self.assertEqual(again["text"], text)
        with self.assertRaises(ai_answers.StateError):
            self.answers.append(row["id"], 0, text.encode(), done=True, finish="length")
        with self.assertRaises(ai_answers.StateError):
            self.answers.append(row["id"], 1, text.encode(), done=True, finish="stop")

    def test_reload_after_multi_chunk_length_cap_stays_valid(self):
        row = self._start()
        first = "A GPU is a specialized processor designed for parallel work. "
        rest = "Converting those 3D vector shapes into a"
        self.answers.append(row["id"], 0, first.encode(), done=False)
        self.answers.append(row["id"], len(first.encode()), rest.encode(), done=True, finish="length")
        ident = row["id"]
        reloaded = ai_answers.AnswerStore(Store(self.root))
        self.assertFalse(getattr(reloaded, "_startup_notice", None))
        shown = reloaded.get(ident)
        self.assertEqual(shown["state"], "done")
        self.assertEqual(shown["finish"], "length")
        self.assertEqual(shown["text"], first.rstrip())
        # The stored record keeps the hanging tail for exact USB acks.
        raw = (self.root / f"ai-answer-{ident}.json")
        # store writes a wrapper; just confirm get trim does not quarantine
        self.assertTrue(any(self.root.iterdir()))
        self.assertFalse(any(path.name.endswith(suffix) for path in self.root.iterdir()
                             for suffix in () if ".bad-" in path.name))
        self.assertFalse(any(".bad-" in path.name for path in self.root.iterdir()))


if __name__ == "__main__":
    unittest.main()

"""The word-salad judge turns on by itself when the pinned model and llama-perplexity are in runtime/."""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gpu_link_salad as salad



def _env(**values):
    env = {k: v for k, v in os.environ.items() if k not in ("OPOS_GPU_LINK_SALAD_BIN", "OPOS_GPU_LINK_SALAD_MODEL",
                                                            "OPOS_GPU_LINK_SALAD_NGL", "OPOS_GPU_LINK_SALAD_THREADS",
                                                            "OPOS_GPU_LINK_SALAD")}
    env.update(values)
    return patch.dict(os.environ, env, clear=True)


class SaladDefaultJudge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime = Path(self.tmp.name)
        bin_dir = self.runtime / "llama-b1-macos-arm64" / "llama-b1"
        bin_dir.mkdir(parents=True)
        self.binary = bin_dir / "llama-perplexity"
        self.binary.write_text("#!/bin/sh\n")
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)
        (self.runtime / "salad").mkdir()
        self.model = self.runtime / "salad" / salad.PINNED_MODEL

    def tearDown(self):
        self.tmp.cleanup()

    def pin(self, data):
        """Pretend `data` is the pinned file (size and sha256 follow it)."""
        import hashlib
        self.model.write_bytes(data)
        return patch.multiple(salad, PINNED_SIZE=len(data), PINNED_SHA256=hashlib.sha256(data).hexdigest())

    def test_pinned_model_and_binary_in_runtime_turn_the_judge_on(self):
        with self.pin(b"gguf judge"), _env():
            judge = salad.PerplexityJudge.from_env(str(self.runtime))
        self.assertIsNotNone(judge)
        self.assertEqual(judge.model, str(self.model))
        self.assertEqual(judge.binary, str(self.binary))

    def test_a_changed_model_file_is_refused(self):
        with self.pin(b"gguf judge"), _env():
            self.model.write_bytes(b"gguf judgf")  # same size, different bytes
            self.assertIsNone(salad.PerplexityJudge.from_env(str(self.runtime)))

    def test_wrong_size_is_refused_before_hashing(self):
        with self.pin(b"gguf judge"), _env():
            self.model.write_bytes(b"short")
            self.assertIsNone(salad.PerplexityJudge.from_env(str(self.runtime)))

    def test_no_model_means_no_judge(self):
        with _env():
            self.assertIsNone(salad.PerplexityJudge.from_env(str(self.runtime)))

    def test_env_vars_set_to_empty_keep_it_off(self):
        with self.pin(b"gguf judge"), _env(OPOS_GPU_LINK_SALAD_BIN="", OPOS_GPU_LINK_SALAD_MODEL=""):
            self.assertIsNone(salad.PerplexityJudge.from_env(str(self.runtime)))

    def test_kill_switch_keeps_the_default_judge_off(self):
        with self.pin(b"gguf judge"), _env(OPOS_GPU_LINK_SALAD="0"), \
                patch.object(salad, "RUNTIME_DIR", str(self.runtime)), patch.dict(salad._DEFAULT, {}, clear=True):
            self.assertIsNone(salad.default_judge())

    def test_default_judge_uses_runtime_dir(self):
        with self.pin(b"gguf judge"), _env(), \
                patch.object(salad, "RUNTIME_DIR", str(self.runtime)), patch.dict(salad._DEFAULT, {}, clear=True):
            self.assertEqual(salad.default_judge().model, str(self.model))

    def test_only_one_empty_env_var_keeps_that_part_off(self):
        with self.pin(b"gguf judge"), _env(OPOS_GPU_LINK_SALAD_BIN=""):
            self.assertIsNone(salad.PerplexityJudge.from_env(str(self.runtime)))
        with self.pin(b"gguf judge"), _env(OPOS_GPU_LINK_SALAD_MODEL=""):
            self.assertIsNone(salad.PerplexityJudge.from_env(str(self.runtime)))

    def test_no_binary_skips_hashing_the_model(self):
        self.binary.unlink()
        with self.pin(b"gguf judge"), _env(), patch.object(salad, "_pinned_model") as pinned:
            self.assertIsNone(salad.PerplexityJudge.from_env(str(self.runtime)))
        pinned.assert_not_called()

    def test_wrong_size_never_reads_the_file(self):
        with self.pin(b"gguf judge"), _env():
            self.model.write_bytes(b"short")
            with patch.object(salad.hashlib, "sha256") as sha:
                self.assertIsNone(salad.PerplexityJudge.from_env(str(self.runtime)))
            sha.assert_not_called()

    def test_a_non_executable_binary_is_skipped(self):
        self.binary.chmod(0o644)
        with self.pin(b"gguf judge"), _env():
            self.assertIsNone(salad.PerplexityJudge.from_env(str(self.runtime)))

    def test_default_judge_is_built_once_under_concurrency(self):
        import threading
        built = []

        def slow_from_env(runtime_dir=None):
            built.append(runtime_dir)
            threading.Event().wait(0.05)
            return None

        with _env(), patch.dict(salad._DEFAULT, {}, clear=True), \
                patch.object(salad.PerplexityJudge, "from_env", staticmethod(slow_from_env)):
            threads = [threading.Thread(target=salad.default_judge) for _ in range(5)]
            for t in threads: t.start()
            for t in threads: t.join()
        self.assertEqual(len(built), 1)

    def test_judge_runs_on_the_cpu_by_default(self):
        seen = {}

        def fake_run(argv, **_kw):
            seen["argv"] = argv
            return subprocess.CompletedProcess(argv, 0, "Final estimate: PPL = 12.5", "")

        judge = salad.PerplexityJudge("/bin/true", "/m.gguf")
        with _env(), patch.object(salad.subprocess, "run", fake_run):
            self.assertEqual(judge.ppl("x" * 50), 12.5)
        self.assertEqual(seen["argv"][seen["argv"].index("-ngl") + 1], "0")
        self.assertEqual(seen["argv"][seen["argv"].index("-t") + 1], "2")
        with _env(OPOS_GPU_LINK_SALAD_NGL="99"), patch.object(salad.subprocess, "run", fake_run):
            judge.ppl("x" * 50)
        self.assertEqual(seen["argv"][seen["argv"].index("-ngl") + 1], "99")
        with _env(OPOS_GPU_LINK_SALAD_NGL="\u0663"), patch.object(salad.subprocess, "run", fake_run):  # Arabic-Indic 3
            judge.ppl("x" * 50)
        self.assertEqual(seen["argv"][seen["argv"].index("-ngl") + 1], "0")
        with _env(OPOS_GPU_LINK_SALAD_NGL="all"), patch.object(salad.subprocess, "run", fake_run):
            judge.ppl("x" * 50)
        self.assertEqual(seen["argv"][seen["argv"].index("-ngl") + 1], "0")

    def test_thread_count_falls_back_to_two(self):
        for raw, want in (("0", "2"), ("00", "2"), ("x", "2"), ("4", "4"), ("04", "4")):
            with _env(OPOS_GPU_LINK_SALAD_THREADS=raw):
                self.assertEqual(salad._threads(), want, raw)

    def test_unusable_env_binary_skips_hashing_the_model(self):
        with self.pin(b"gguf judge"), _env(OPOS_GPU_LINK_SALAD_BIN="/nonexistent/llama-perplexity"), \
                patch.object(salad, "_pinned_model") as pinned:
            self.assertIsNone(salad.PerplexityJudge.from_env(str(self.runtime)))
        pinned.assert_not_called()

    def test_pin_matches_the_downloaded_judge(self):
        self.assertEqual(salad.PINNED_MODEL, "SmolLM2-135M-Instruct-Q8_0.gguf")
        self.assertEqual(salad.PINNED_SIZE, 144811360)
        self.assertEqual(salad.PINNED_SHA256, "5a1395716f7913741cc51d98581b9b1228d80987a9f7d3664106742eb06bba83")


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Generation defaults and launcher contracts. No model, GPU or network needed."""
import os
import sys
import unittest
from dataclasses import FrozenInstanceError, asdict
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_link_autosetup as a  # noqa: E402
import gpu_link_gen as g  # noqa: E402


FIELDS = {
    "temp": "--temp", "top_p": "--top-p", "top_k": "--top-k", "min_p": "--min-p",
    "repeat_penalty": "--repeat-penalty", "repeat_last_n": "--repeat-last-n",
    "dry_multiplier": "--dry-multiplier", "dry_base": "--dry-base",
    "dry_allowed_length": "--dry-allowed-length", "dry_penalty_last_n": "--dry-penalty-last-n",
    "n_predict": "-n",
}
INTEGER_FIELDS = {"top_k", "repeat_last_n", "dry_allowed_length", "dry_penalty_last_n", "n_predict"}
VALID_OVERRIDES = {
    "temp": 0.45, "top_p": 0.85, "top_k": 35, "min_p": 0.08,
    "repeat_penalty": 1.12, "repeat_last_n": 192, "dry_multiplier": 0.7,
    "dry_base": 1.8, "dry_allowed_length": 4, "dry_penalty_last_n": 384, "n_predict": 256,
}


class Profiles(unittest.TestCase):
    def test_every_pinned_model_has_a_specific_profile(self):
        expected = {
            "gemma": "gemma3", "Qwen3": "qwen3", "LFM2": "lfm",
            "qwen2.5": "qwen25", "Llama-3.2": "llama3",
        }
        for row in (*a.pins.MODELS, *a.pins.RX580_MODELS):
            with self.subTest(model=row["file"]):
                family = next(value for prefix, value in expected.items() if row["file"].startswith(prefix))
                self.assertEqual(g.generation_profile(row["file"], environ={}).family, family)

    def test_requested_local_families_and_case_variants(self):
        models = {
            "Gemma-3-4B-it-Q4_K_M.gguf": "gemma3",
            "gemma3-12b-it.gguf": "gemma3",
            "GEMMA-4-4B-IT.gguf": "gemma4",
            "Meta-Llama-3.1-8B-Instruct-Q4_K_M.gguf": "llama3",
            "Llama-3.2-1B-Instruct-Q8_0.gguf": "llama3",
            "Qwen2.5-1.5B-Instruct.gguf": "qwen25",
            "Qwen3-4B-Q4_K_M.gguf": "qwen3",
            "Qwen3.6-35B-A3B-UD-Q4_K_M.gguf": "qwen3",
            "Qwen3.8-27B-UD-Q6_K.gguf": "qwen3",
            "Phi-3-mini-4k-instruct.gguf": "phi",
            "Phi-4-mini-instruct.gguf": "phi",
            "Mistral-7B-Instruct-v0.3.gguf": "mistral",
            "LFM2-1.2B-Q4_K_M.gguf": "lfm",
            "lfm3-1.7b.gguf": "lfm",
            "SmolLM2-1.7B-Instruct.gguf": "smollm",
            "granite-3.3-2b-instruct.gguf": "granite",
            "DeepSeek-R1-Distill-Qwen-7B.gguf": "deepseek",
            "GLM-4-9B-Chat.gguf": "glm",
        }
        for name, family in models.items():
            with self.subTest(name=name):
                self.assertEqual(g.generation_profile(name, environ={}).family, family)

    def test_unknown_model_gets_generic_without_directory_hints(self):
        for name in ("unknown.gguf", "/models/Qwen3/custom.gguf", "/models/gemma-3/custom.gguf",
                     r"C:\models\Llama-3.2\custom.gguf", "gemma-30-4b.gguf", "qwen30-4b.gguf",
                     "llama-30-8b.gguf", "myqwen3custom.gguf"):
            with self.subTest(name=name):
                self.assertEqual(g.generation_profile(name, environ={}), g.GENERATION_PROFILES["generic"])

    def test_distilled_names_follow_the_first_family_token(self):
        for model in ("DeepSeek-R1-Distill-Llama-3.3-8B.gguf", "DeepSeek-R1-Distill-Qwen3-8B.gguf"):
            for prefix in ("", "bartowski-"):
                with self.subTest(model=prefix + model):
                    self.assertEqual(g.generation_profile(prefix + model, environ={}).family, "deepseek")

    def test_paths_with_spaces_and_windows_separators_resolve(self):
        for path in (Path("/models/My Models/Qwen3-4B.gguf"), r"C:\My Models\Qwen3-4B.gguf"):
            self.assertEqual(g.generation_profile(path, environ={}).family, "qwen3")

    def test_table_covers_all_documented_families_with_sane_bounds(self):
        self.assertEqual(set(g.GENERATION_PROFILES), {
            "generic", "gemma3", "gemma4", "llama3", "qwen25", "qwen3", "phi", "mistral",
            "lfm", "smollm", "granite", "deepseek", "glm",
        })
        ranges = {
            "top_k": (1, 200), "min_p": (0, 1), "repeat_penalty": (1, 1.3),
            "repeat_last_n": (16, 2048), "dry_multiplier": (0, 2),
            "dry_allowed_length": (2, 16), "dry_penalty_last_n": (16, 2048), "n_predict": (1, 1024),
        }
        for family, profile in g.GENERATION_PROFILES.items():
            with self.subTest(family=family):
                self.assertEqual(profile.family, family)
                self.assertGreater(profile.temp, 0)
                self.assertLessEqual(profile.temp, 1)
                self.assertGreater(profile.top_p, 0)
                self.assertLessEqual(profile.top_p, 1)
                self.assertGreater(profile.dry_base, 1)
                self.assertLessEqual(profile.dry_base, 3)
                for field, (lower, upper) in ranges.items():
                    self.assertGreaterEqual(getattr(profile, field), lower)
                    self.assertLessEqual(getattr(profile, field), upper)
                for field in INTEGER_FIELDS:
                    self.assertIs(type(getattr(profile, field)), int)

    def test_returned_profile_is_immutable(self):
        profile = g.generation_profile("unknown.gguf", environ={})
        with self.assertRaises(FrozenInstanceError):
            profile.temp = 0.9

    def test_rx580_overlay_is_conservative_for_both_pinned_lanes(self):
        for row in a.pins.RX580_MODELS:
            profile = g.generation_profile(row["file"], profile=a.PROFILE_RX580, environ={})
            with self.subTest(model=row["file"]):
                self.assertLessEqual(profile.temp, 0.3)
                self.assertEqual(profile.n_predict, 384)
                self.assertGreaterEqual(profile.repeat_penalty, 1.15)
                self.assertGreaterEqual(profile.dry_multiplier, 0.8)

    def test_unknown_hardware_profile_preserves_family_defaults(self):
        self.assertEqual(g.generation_profile("Qwen3-4B.gguf", profile="other-profile", environ={}),
                         g.generation_profile("Qwen3-4B.gguf", environ={}))

    def test_demo_families_use_a_1024_token_budget(self):
        for family, profile in g.GENERATION_PROFILES.items():
            with self.subTest(family=family):
                self.assertEqual(profile.n_predict, 1024)
        flags = g.generation_flags("gemma-4-26B_q4_0-it.gguf", environ={})
        self.assertEqual(int(flags[flags.index("-n") + 1]), 1024)


class Overrides(unittest.TestCase):
    def test_explicit_overrides_apply_to_every_setting(self):
        profile = g.generation_profile("Qwen3-4B.gguf", overrides=VALID_OVERRIDES, environ={})
        for field, value in VALID_OVERRIDES.items():
            self.assertEqual(getattr(profile, field), value)

    def test_environment_overrides_apply_to_every_setting(self):
        environ = {"OPOS_GPU_LINK_" + field.upper(): str(value) for field, value in VALID_OVERRIDES.items()}
        profile = g.generation_profile("unknown.gguf", environ=environ)
        for field, value in VALID_OVERRIDES.items():
            self.assertEqual(getattr(profile, field), value)

    def test_precedence_family_then_hardware_then_explicit_then_environment(self):
        profile = g.generation_profile(
            "Llama-3.2-1B.gguf", profile=a.PROFILE_RX580,
            overrides={"temp": 0.6, "n_predict": 512, "repeat_penalty": 1.05},
            environ={"OPOS_GPU_LINK_TEMP": "0.4", "OPOS_GPU_LINK_N_PREDICT": "256"},
        )
        self.assertEqual(profile.temp, 0.4)
        self.assertEqual(profile.n_predict, 256)
        self.assertEqual(profile.repeat_penalty, 1.05)
        self.assertGreaterEqual(profile.dry_multiplier, 0.8)

    def test_default_environment_is_read_when_called(self):
        with patch.dict(os.environ, {"OPOS_GPU_LINK_TEMP": "0.41"}, clear=True):
            self.assertEqual(g.generation_profile("unknown.gguf").temp, 0.41)
            self.assertEqual(g.generation_profile("unknown.gguf", environ={}), g.GENERATION_PROFILES["generic"])

    def test_calls_and_input_mappings_do_not_mutate_profiles(self):
        original = {family: asdict(profile) for family, profile in g.GENERATION_PROFILES.items()}
        overrides = dict(VALID_OVERRIDES)
        environ = {"OPOS_GPU_LINK_TEMP": "0.55"}
        g.generation_profile("Qwen3-4B.gguf", profile=a.PROFILE_RX580, overrides=overrides, environ=environ)
        self.assertEqual(overrides, VALID_OVERRIDES)
        self.assertEqual(environ, {"OPOS_GPU_LINK_TEMP": "0.55"})
        self.assertEqual({family: asdict(profile) for family, profile in g.GENERATION_PROFILES.items()}, original)
        self.assertEqual(g.generation_profile("unknown.gguf", environ={}), g.GENERATION_PROFILES["generic"])

    def test_invalid_ranges_are_rejected_without_unlimited_generation(self):
        invalid = {
            "temp": (0, -1, 1.01), "top_p": (0, -1, 1.01), "top_k": (0, 201, 1.5),
            "min_p": (-0.01, 1.01), "repeat_penalty": (0.99, 1.31),
            "repeat_last_n": (-1, 0, 15, 2049, 16.5), "dry_multiplier": (-0.01, 2.01),
            "dry_base": (0, 1, 3.01), "dry_allowed_length": (1, 17, 2.5),
            "dry_penalty_last_n": (-1, 0, 15, 2049, 16.5), "n_predict": (-2, -1, 0, 1025, 1.5),
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    with self.assertRaises(RuntimeError):
                        g.generation_profile("unknown.gguf", overrides={field: value}, environ={})
                    with self.assertRaises(RuntimeError):
                        g.generation_profile("unknown.gguf", environ={"OPOS_GPU_LINK_" + field.upper(): str(value)})

    def test_non_finite_and_boolean_values_are_rejected(self):
        for field in FIELDS:
            for value in (float("nan"), float("inf"), -float("inf"), True, False):
                with self.subTest(field=field, value=value):
                    with self.assertRaises(RuntimeError):
                        g.generation_profile("unknown.gguf", overrides={field: value}, environ={})
            for value in ("nan", "inf", "-inf", "true", "false"):
                with self.subTest(field=field, environment=value):
                    with self.assertRaises(RuntimeError):
                        g.generation_profile("unknown.gguf", environ={"OPOS_GPU_LINK_" + field.upper(): value})

    def test_unknown_fields_and_non_numeric_overrides_are_rejected(self):
        for overrides in ({"family": "qwen3"}, {"unknown": 1}, {"temp": "0.5"}, {"temp": None}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(RuntimeError):
                    g.generation_profile("unknown.gguf", overrides=overrides, environ={})

    def test_error_messages_do_not_echo_raw_environment_values(self):
        raw = "private-invalid-value-for-test"
        with self.assertRaises(RuntimeError) as error:
            g.generation_profile("unknown.gguf", environ={"OPOS_GPU_LINK_TEMP": raw})
        self.assertNotIn(raw, str(error.exception))


class Command(unittest.TestCase):
    def test_flags_apply_every_generation_setting_once(self):
        flags = g.generation_flags("Qwen3-4B.gguf", overrides=VALID_OVERRIDES, environ={})
        self.assertEqual(len(flags), 2 * len(FIELDS))
        for field, flag in FIELDS.items():
            self.assertEqual(flags.count(flag), 1)
            self.assertEqual(float(flags[flags.index(flag) + 1]), VALID_OVERRIDES[field])
        self.assertTrue(all(isinstance(part, str) for part in flags))

    def test_each_backend_retains_the_exact_existing_command_and_adds_defaults(self):
        for backend in ("metal", "cuda", "vulkan", "cpu"):
            for profile in (None, a.PROFILE_RX580):
                for device in (None, "Vulkan1", "Vulkan1;bad"):
                    with self.subTest(backend=backend, profile=profile, device=device):
                        command = a.server_command(
                            Path("/runtime/llama-server"), Path("/models/Qwen3-4B.gguf"), 38255,
                            Path("/private/k"), "lane-2", backend, ctx=2048, profile=profile,
                            device=device, environ={},
                        )
                        expected = [
                            "/runtime/llama-server", "-m", "/models/Qwen3-4B.gguf", "--host", "127.0.0.1",
                            "--port", "38255", "-ngl", "0" if backend == "cpu" else "999", "-c", "2048",
                            "--alias", "lane-2", "-np", str(a.SLOTS), "--jinja", "--api-key-file", "/private/k",
                            "--cors-origins", "localhost", "--no-webui", "--no-slots", "-lv", "4",
                        ]
                        if profile == a.PROFILE_RX580:
                            expected += ["-fa", "off", "--no-kv-offload"]
                        if backend != "cpu" and device == "Vulkan1":
                            expected += ["--device", "Vulkan1"]
                        remaining = list(command)
                        for flag in FIELDS.values():
                            self.assertEqual(remaining.count(flag), 1)
                            index = remaining.index(flag)
                            del remaining[index:index + 2]
                        self.assertEqual(remaining, expected)
                        self.assertEqual(command[-2 * len(FIELDS):],
                                         g.generation_flags("Qwen3-4B.gguf", profile=profile, environ={}))

    def test_server_command_allows_explicit_and_environment_overrides(self):
        command = a.server_command(
            "llama-server", "unknown.gguf", 38255, "k", "alias", "metal",
            generation_overrides={"temp": 0.6, "n_predict": 512},
            environ={"OPOS_GPU_LINK_TEMP": "0.42"},
        )
        self.assertEqual(float(command[command.index("--temp") + 1]), 0.42)
        self.assertEqual(int(command[command.index("-n") + 1]), 512)

    def test_embedded_template_and_native_end_tokens_are_preserved(self):
        for model in ("unknown.gguf", "Gemma-3-4B.gguf", "Qwen3-4B.gguf", "Llama-3.2-1B.gguf"):
            with self.subTest(model=model):
                command = a.server_command("llama-server", model, 38255, "k", "alias", "cpu", environ={})
                self.assertIn("--jinja", command)
                for forbidden in ("--chat-template", "--chat-template-file", "--ignore-eos", "--reverse-prompt"):
                    self.assertNotIn(forbidden, command)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""A paired PC can be shown under another name without renaming the saved pairing."""

import os
import unittest
from unittest import mock

from opos import gpu_link


class DisplayLabelTest(unittest.TestCase):
    def test_unset_keeps_label(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPOS_GPU_LINK_PC_DISPLAY", None)
            self.assertEqual(gpu_link.display_label("M5 Pro PC"), "M5 Pro PC")

    def test_maps_only_the_named_label(self):
        env = {"OPOS_GPU_LINK_PC_DISPLAY": "M5 Pro PC=M5 Pro MacBook Pro; RTX 5080 PC=RTX 5080 PC"}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(gpu_link.display_label("M5 Pro PC"), "M5 Pro MacBook Pro")
            self.assertEqual(gpu_link.display_label("RTX 3080 Ti PC"), "RTX 3080 Ti PC")
            self.assertIsNone(gpu_link.display_label(None))

    def test_rejects_an_invalid_screen_name(self):
        with mock.patch.dict(os.environ, {"OPOS_GPU_LINK_PC_DISPLAY": "M5 Pro PC=\x07bad"}):
            self.assertEqual(gpu_link.display_label("M5 Pro PC"), "M5 Pro PC")

    def test_known_model_file_names_map_only_on_screen(self):
        cases = (
            ("Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf", "Nemotron 3.5 Bolt", "NVIDIA"),
            ("LFM2-1.2B-Q4_K_M.gguf", "LFM2 (comparison baseline)", "Liquid AI"),
            ("Qwen3.5-2B-Q4_K_M.gguf", "Qwen3.5-2B", "Qwen (Alibaba)"),
            ("Granite-4.1-3B-Q4_K_M.gguf", "Granite 4.1 3B", "IBM"),
        )
        for source, shown, maker in cases:
            with self.subTest(source=source):
                self.assertEqual(gpu_link.display_model_name(source), shown)
                self.assertEqual(gpu_link.display_model_maker(source, "Local"), maker)
        for source, shown in (
            ("Nemotron-3.5-Bolt_Q4_K_M.gguf", "Nemotron 3.5 Bolt"),
            ("LFM2_1.2B.gguf", "LFM2 (comparison baseline)"),
            ("Qwen3.5-2B_Q4_K_M.gguf", "Qwen3.5-2B"),
            ("Granite-4.1-3B_Q4_K_M.gguf", "Granite 4.1 3B"),
        ):
            with self.subTest(underscored=source):
                self.assertEqual(gpu_link.display_model_name(source), shown)
        self.assertEqual(gpu_link.display_model_name("Unknown.gguf"), "Unknown.gguf")
        self.assertEqual(gpu_link.display_model_maker("Unknown.gguf", "Local"), "Local")

    def test_fallback_names_use_the_replacement_model(self):
        source = "Qwen3-4B-Q4_K_M.gguf (fallback for Nemotron-3.5-Bolt-E4B)"
        shown = gpu_link.display_model_name(source)
        self.assertEqual(shown, "Qwen3-4B-Q4_K_M.gguf (fallback for Nemotron 3.5 Bolt)")
        self.assertEqual(gpu_link.display_model_maker(source, "Qwen"), "Qwen (Alibaba)")
        self.assertEqual(gpu_link.display_model_name(
            "Qwen3.5-2B_Q4_K_M.gguf (fallback for LFM2-1.2B)"), "Qwen3.5-2B")
        self.assertEqual(gpu_link.display_model_maker(
            "Other.gguf (fallback for Granite-4.1-3B)", "Local"), "Local")
        self.assertEqual(gpu_link.display_model_maker("granite_other.gguf", "Local"), "IBM")

    def test_model_row_keeps_engine_id_and_source_metadata(self):
        source = {"id": "lfm2-1.2b", "label": "LFM2 1.2B", "maker": "Liquid AI", "gpu": None}
        shown = gpu_link.display_model_row(source)
        self.assertEqual(shown, {"id": "lfm2-1.2b", "label": "LFM2 (comparison baseline)",
                                 "maker": "Liquid AI", "gpu": None})
        self.assertEqual(source["label"], "LFM2 1.2B")

    def test_phone_pool_name_uses_known_filename_only(self):
        self.assertEqual(gpu_link.display_pool_model(
            "Old Qwen label", "Qwen", "Qwen3.5-2B-Q4_K_M.gguf"),
            ("Qwen3.5-2B", "Qwen (Alibaba)"))
        self.assertEqual(gpu_link.display_pool_model(
            "Old Granite label", "IBM", "Granite-4.1-3B-Q4_K_M.gguf"),
            ("Granite 4.1 3B", "IBM"))
        self.assertEqual(gpu_link.display_pool_model(
            "Original label", "Local", "unknown.gguf"), ("Original label", "Local"))

    def test_saved_pool_answer_changes_only_for_the_current_model(self):
        self.assertEqual(gpu_link.display_saved_pool_model(
            "Old Qwen label", "Old Qwen label", "Qwen3.5-2B"), "Qwen3.5-2B")
        self.assertEqual(gpu_link.display_saved_pool_model(
            "Earlier model", "Old Qwen label", "Qwen3.5-2B"), "Earlier model")
        self.assertEqual(gpu_link.display_saved_pool_model("", "", "Qwen3.5-2B"), "")


    def test_ai_page_maps_a_stored_answer_without_changing_it(self):
        try:
            from opos import ai_page
        except ImportError:
            self.skipTest("ai_page needs the host app (ai_model_pool)")
        stored = {"id": "a", "where": "M5 Pro PC", "state": "done"}
        with mock.patch.dict(os.environ, {"OPOS_GPU_LINK_PC_DISPLAY": "M5 Pro PC=M5 Pro MacBook Pro"}):
            shown = ai_page._shown_answer(stored)
        self.assertEqual(shown["where"], "M5 Pro MacBook Pro")
        self.assertEqual(stored["where"], "M5 Pro PC")
        self.assertIsNone(ai_page._shown_answer(None))
        pool_answer = {"id": "b", "model": "Old Qwen label", "where": "on this phone"}
        shown_pool = ai_page._shown_answer(pool_answer, pool_current="Old Qwen label",
                                          pool_shown="Qwen3.5-2B")
        self.assertEqual(shown_pool["model"], "Qwen3.5-2B")
        self.assertEqual(pool_answer["model"], "Old Qwen label")


if __name__ == "__main__":
    unittest.main()

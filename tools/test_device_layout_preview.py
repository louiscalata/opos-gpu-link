"""Offline checks for the four static layout mocks."""

import importlib.util
from pathlib import Path
import struct
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("device-layout-preview.py")
SPEC = importlib.util.spec_from_file_location("device_layout_preview", SCRIPT)
preview = importlib.util.module_from_spec(SPEC)
import sys
sys.modules[SPEC.name] = preview
SPEC.loader.exec_module(preview)


class DeviceLayoutPreviewTest(unittest.TestCase):
    def test_column_math_reads_android_policy(self):
        threshold = preview.column_threshold()
        self.assertEqual(1, preview.column_count(threshold - 1, cover=False, lane_count=4))
        self.assertEqual(2, preview.column_count(threshold, cover=False, lane_count=4))
        self.assertEqual(1, preview.column_count(threshold, cover=False, lane_count=1))
        self.assertEqual(1, preview.column_count(threshold, cover=True, lane_count=4))
        self.assertEqual(1, preview.column_count(360, cover=False, lane_count=4))
        self.assertEqual(2, preview.column_count(880, cover=False, lane_count=4))
        self.assertEqual((1.1, 0.9, 1.4), preview.band_weights())

    def test_phone_is_left_and_machine_is_right(self):
        for scene in (preview.inner_scene(1080, 2640, landscape=False),
                      preview.inner_scene(2640, 1080, landscape=True)):
            texts = [op.args for op in scene.operations if op.kind == "text"]
            phone_x = next(args[0] for args in texts if args[2] == "PHONE")
            machine_x = next(args[0] for args in texts
                             if args[2] == "COMPUTER")
            self.assertLess(phone_x, machine_x)
            band_y = next(args[1] for args in texts if args[2] == "PHONE")
            question_y = next(args[1] for args in texts if args[2] == "YOUR QUESTION")
            self.assertLess(band_y, question_y)
            self.assertIn("MOCK PREVIEW", scene.svg())
            self.assertIn("Scroll for more answers", scene.svg())
        for scene, phone, machine in (
            (preview.cover_scene(), "Phone", "MacBook"),
            (preview.tk_scene(), "PHONE", "THIS COMPUTER"),
        ):
            texts = [op.args for op in scene.operations if op.kind == "text"]
            phone_x = next(args[0] for args in texts if args[2] == phone)
            machine_x = next(args[0] for args in texts if args[2] == machine)
            self.assertLess(phone_x, machine_x)
            self.assertIn("MOCK PREVIEW", scene.svg())

    def test_landscape_card_columns_match_android_free_space_rule(self):
        source = preview.POLICY.read_text(encoding="utf-8")
        self.assertIn("side == Side.PHONE && phoneCards > computerCards", source)
        self.assertIn("side == Side.COMPUTER && computerCards > phoneCards", source)
        self.assertEqual({
            "Qwen3.5-2B": "left",
            "Nemotron 3.5 Bolt": "right",
            "Granite 4.1 3B": "left",
            "LFM2": "right",
        }, preview.place_demo_lanes())
        scene = preview.inner_scene(2640, 1080, landscape=True)
        headings = {op.args[2]: op.args[0] for op in scene.operations
                    if op.kind == "text" and op.args[2] in preview.place_demo_lanes()}
        self.assertEqual(headings["Qwen3.5-2B"], headings["Granite 4.1 3B"])
        self.assertEqual(headings["Nemotron 3.5 Bolt"], headings["LFM2"])
        self.assertLess(headings["Qwen3.5-2B"], headings["Nemotron 3.5 Bolt"])
        self.assertIn("PHONE · COMPARISON BASELINE", scene.svg())

    def test_cover_has_composer_and_pinned_summary_without_clipping(self):
        scene = preview.cover_scene()
        labels = [op.args[2] for op in scene.operations if op.kind == "text"]
        for label in ("Ask the models…", "Send", "NOTES", "SUMMARY"):
            self.assertIn(label, labels)
        for op in scene.operations:
            if op.kind == "rect":
                _, y, _, height, *_ = op.args
                self.assertLessEqual(y + height, scene.height)
            elif op.kind == "text":
                _, y, _, size, *_ = op.args
                self.assertLessEqual(y + size, scene.height)

    def test_standard_library_fallback_writes_valid_png(self):
        scene = preview.cover_scene()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "mock-cover.png"
            preview._stdlib_png(scene, path)
            data = path.read_bytes()
        self.assertTrue(data.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertEqual((720, 748), struct.unpack(">II", data[16:24]))

    def test_four_preview_files_have_expected_dimensions(self):
        with tempfile.TemporaryDirectory() as directory:
            outputs = preview.generate(Path(directory))
            self.assertEqual(4, len(outputs))
            dimensions = {
                path.name: struct.unpack(">II", path.read_bytes()[16:24])
                for path, _ in outputs
            }
        self.assertEqual({
            "mock-inner-portrait.png": (1080, 2640),
            "mock-inner-landscape.png": (2640, 1080),
            "mock-cover.png": (720, 748),
            "mock-mac-companion.png": (1100, 720),
        }, dimensions)


if __name__ == "__main__":
    unittest.main()

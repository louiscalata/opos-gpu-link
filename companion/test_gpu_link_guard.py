"""Network/GPU-free fixtures for conservative runtime output guards."""
from pathlib import Path
import unittest

import gpu_link_guard as guard


PROSE = (
    "A GPU renders a frame by taking vertices, transforming them, rasterizing triangles into fragments, shading each "
    "fragment with textures and lights, testing depth, blending, and finally writing the colours to a frame buffer "
    "that the display reads. Each stage runs in parallel across thousands of small cores. "
) * 6

GOOD = (
    "", "short", "Yes.", "ha ha ha ha", "ha ha ha ha ha ha ha ha", PROSE,
    PROSE + "\n" + "-" * 80 + "\n" + "=" * 60 + "\n" + "." * 60,
    "| Name | Value |\n" + "|---" * 9 + "|\n| Frame | 42 |",
    "# Rendering\n1. Transform vertices.\n2. Rasterize triangles.\n3. Shade pixels.\n",
    "El procesador gráfico dibuja triángulos y calcula los colores de cada píxel.",
    "图形处理器把顶点转换为三角形，再计算每个像素的颜色。",
    "グラフィックス処理装置は頂点を変換し、ピクセルの色を計算します。",
    "```python\nfor i in range(10):\n    print(i * i)\n```\n",
    "```java\nint square(int x) { return x * x; }\n```\n",
    "E = mc²; ∑ᵢ xᵢ = 10; y = sin(x) + π / 2.\n2 + 2 = 4.",
    "The shader reads `texture(u, v)` and returns vec4(r, g, b, 1.0).",
    "\n\t" * 80,
)


class GarbleReasonTests(unittest.TestCase):
    def test_known_good_fixtures(self):
        for text in GOOD:
            with self.subTest(text=text[:60]):
                self.assertIsNone(guard.garble_reason(text))
                self.assertIsNone(guard.garble_reason(text, final=True))

    def test_rx580_repeated_character_fixtures(self):
        for bad in ("-@" + "@" * 3551, "8" * 200):
            with self.subTest(bad=bad[:10]):
                self.assertEqual(guard.garble_reason(PROSE + bad, final=True), "repeat_char")

    def test_repeat_reason_takes_precedence_over_symbol_density(self):
        self.assertEqual(guard.garble_reason(PROSE + "-@" + "@" * 400), "repeat_char")

    def test_rx580_fragment_fixtures(self):
        for count in (8, 120):
            with self.subTest(count=count):
                self.assertEqual(guard.garble_reason(PROSE + "asks8alion" * count), "ngram_loop")

    def test_longer_character_fragment(self):
        self.assertEqual(guard.garble_reason("renderVertexBufferAgain" * 8), "ngram_loop")

    def test_word_loop_with_varying_whitespace(self):
        text = " ".join("red" + " " * (index % 3 + 1) + "blue green" for index in range(10))
        self.assertEqual(guard.garble_reason(text), "ngram_loop")

    def test_multiword_sentence_loop(self):
        self.assertEqual(guard.garble_reason("The GPU draws a triangle. " * 12), "ngram_loop")

    def test_control_characters(self):
        self.assertEqual(guard.garble_reason("\x01\x02\x03\x04" * 30), "non_text")

    def test_symbol_garbage_after_prose(self):
        self.assertEqual(guard.garble_reason("Good answer.\n" + "👾🔥💥🌀" * 30), "non_text")

    def test_ascii_symbol_garbage(self):
        self.assertEqual(guard.garble_reason("@!?$%&" * 20), "non_text")

    def test_encoding_junk(self):
        for junk in ("\x00", "\ufffd" * 8, "cafÃ©", "itâ€™s", "Â©", "ðŸ", "<|im_end|>", "<unused12>"):
            with self.subTest(junk=junk):
                self.assertEqual(guard.garble_reason("An answer " + junk), "encoding_junk")

    def test_isolated_accented_letters_are_prose(self):
        self.assertIsNone(guard.garble_reason("São Paulo: Ângela, João e café."))

    def test_total_length_limit(self):
        self.assertIsNone(guard.garble_reason("A useful answer.", max_chars=16))
        self.assertEqual(guard.garble_reason("A useful answer.", max_chars=15), "runaway_length")

    def test_length_check_uses_total_length_not_only_tail(self):
        text = PROSE * 8
        self.assertEqual(guard.garble_reason(text), "runaway_length")

    def test_negative_limit_rejected(self):
        with self.assertRaises(ValueError):
            guard.garble_reason("", max_chars=-1)

    def test_read_only_actual_rx580_receipts(self):
        directory = Path(__file__).resolve().parent.parent / "receipts/macpro-rx580-long/texts"
        if not directory.is_dir():
            self.skipTest("lab recordings are not shipped in the public tree")
        cases = {
            "A_qwen_alone.qwen.txt": "repeat_char",
            "E_llama_default.llama.txt": "ngram_loop",
            "D_nokvoffload.qwen.txt": None,
            "E_llama_nokv.llama.txt": None,
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(guard.garble_reason((directory / name).read_text(), final=True), expected)


class GuardStateTests(unittest.TestCase):
    def test_good_fixtures_flush_exactly(self):
        for text in GOOD:
            with self.subTest(text=text[:60]):
                state = guard.GuardState()
                for offset in range(0, len(text), 17):
                    self.assertIsNone(state.feed(text[offset:offset + 17]))
                self.assertIsNone(state.feed("", final=True))
                self.assertEqual(state.safe_text, text)
                self.assertEqual(state.text, text)
                self.assertIsNone(state.detected_at)

    def test_character_detection_fires_early(self):
        state = guard.GuardState()
        state.feed(PROSE)
        for index in range(guard.REPEAT_CHAR_COUNT):
            reason = state.feed("@")
            if index + 1 < guard.REPEAT_CHAR_COUNT:
                self.assertIsNone(reason)
        self.assertEqual(reason, "repeat_char")
        self.assertEqual(state.detected_at, len(PROSE) + guard.REPEAT_CHAR_COUNT)
        self.assertEqual(state.safe_text, PROSE)

    def test_large_symbol_chunk_retains_preceding_sentence_punctuation(self):
        prefix = "A GPU transforms vertices, shades fragments, and presents a completed frame. "
        state = guard.GuardState()
        state.feed(prefix)
        self.assertEqual(state.feed("@" * 200), "repeat_char")
        self.assertEqual(state.safe_text, prefix)

    def test_non_text_retains_preceding_sentence_punctuation(self):
        state = guard.GuardState()
        state.feed("Good answer. ")
        self.assertEqual(state.feed("👾🔥💥🌀" * 30), "non_text")
        self.assertEqual(state.safe_text, "Good answer. ")

    def test_later_encoding_fault_cannot_release_an_earlier_loop(self):
        state = guard.GuardState()
        state.feed("Good answer. ")
        self.assertIsNone(state.feed("@" * (guard.REPEAT_CHAR_COUNT - 1)))
        self.assertEqual(state.feed("@\x00"), "encoding_junk")
        self.assertEqual(state.safe_text, "Good answer. ")

    def test_later_repeat_cannot_release_an_earlier_word_loop(self):
        state = guard.GuardState()
        state.feed("Good answer. ")
        self.assertIsNone(state.feed("asks8alion" * 5))
        self.assertEqual(state.feed("asks8alion" + "@" * 40), "ngram_loop")
        self.assertEqual(state.safe_text, "Good answer. ")

    def test_late_fragment_detection_fires_within_96_characters(self):
        state = guard.GuardState()
        state.feed(PROSE)
        for index, ch in enumerate("asks8alion" * 120):
            if state.feed(ch):
                break
        self.assertEqual(state.reason, "ngram_loop")
        self.assertLessEqual(index + 1, 96)
        self.assertEqual(state.safe_text, PROSE)

    def test_large_chunk_checked_before_bad_tail_can_leave_window(self):
        state = guard.GuardState(max_chars=100000)
        reason = state.feed(PROSE + "@" * 100000 + "Clean looking ending.")
        self.assertEqual(reason, "repeat_char")
        self.assertLessEqual(state.detected_at, len(PROSE) + guard.REPEAT_CHAR_COUNT + guard.CHECK_CHARS)
        self.assertEqual(state.safe_text, PROSE)

    def test_encoding_token_across_chunk_boundary(self):
        state = guard.GuardState()
        self.assertIsNone(state.feed("Good answer. <|im_"))
        self.assertEqual(state.feed("end|>trailing"), "encoding_junk")
        self.assertEqual(state.safe_text, "Good answer. ")

    def test_mojibake_across_chunk_boundary(self):
        state = guard.GuardState()
        state.feed("Good answer. Ã")
        self.assertEqual(state.feed("©"), "encoding_junk")
        self.assertEqual(state.safe_text, "Good answer. ")

    def test_safe_prefix_never_retracts(self):
        state = guard.GuardState()
        previous = ""
        for offset in range(0, len(PROSE), 7):
            state.feed(PROSE[offset:offset + 7])
            self.assertTrue(state.safe_text.startswith(previous))
            previous = state.safe_text
        for ch in "asks8alion" * 8:
            state.feed(ch)
            self.assertTrue(state.safe_text.startswith(previous))
            previous = state.safe_text
        self.assertEqual(state.reason, "ngram_loop")
        self.assertEqual(state.safe_text, PROSE)

    def test_quarantine_is_bounded(self):
        state = guard.GuardState()
        for offset in range(0, len(PROSE), 31):
            state.feed(PROSE[offset:offset + 31])
            self.assertLessEqual(len(state.text) - len(state.safe_text), guard.QUARANTINE_CHARS)
        self.assertLess(len(state.safe_text), len(PROSE))
        state.feed("", final=True)
        self.assertEqual(state.safe_text, PROSE)

    def test_initial_acknowledged_prefix_is_immutable(self):
        prefix = "Previously acknowledged text. " + "@" * 80
        state = guard.GuardState(initial_text=prefix)
        self.assertEqual(state.safe_text, prefix)
        self.assertIsNone(state.feed(" A clean continuation.", final=True))
        self.assertEqual(state.safe_text, prefix + " A clean continuation.")

    def test_failure_preserves_initial_prefix(self):
        prefix = "Accepted café. "
        state = guard.GuardState(initial_text=prefix)
        self.assertEqual(state.feed("8" * 200), "repeat_char")
        self.assertEqual(state.safe_text, prefix)

    def test_reason_and_detection_position_latch(self):
        state = guard.GuardState()
        state.feed("@" * 60)
        before = state.reason, state.detected_at, state.safe_text
        self.assertEqual(state.feed("\x00", final=True), "repeat_char")
        self.assertEqual((state.reason, state.detected_at, state.safe_text), before)

    def test_finished_state_ignores_late_input(self):
        state = guard.GuardState()
        state.feed("Clean answer.", final=True)
        self.assertIsNone(state.feed("@" * 100))
        self.assertEqual(state.safe_text, "Clean answer.")

    def test_length_limit_trims_exactly_at_cap(self):
        state = guard.GuardState(max_chars=20)
        self.assertEqual(state.feed("An informative answer goes here."), "runaway_length")
        self.assertEqual(state.safe_text, "An informative answe")
        self.assertEqual(len(state.safe_text), 20)

    def test_initial_prefix_counts_toward_length(self):
        state = guard.GuardState(initial_text="12345", max_chars=7)
        self.assertEqual(state.feed("67890"), "runaway_length")
        self.assertEqual(state.safe_text, "1234567")

    def test_negative_limit_rejected(self):
        with self.assertRaises(ValueError):
            guard.GuardState(max_chars=-1)


if __name__ == "__main__":
    unittest.main()

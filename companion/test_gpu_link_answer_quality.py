"""degenerate_text: the e2e must not pass a lane whose long answer turns to garbage (Mac Pro RX 580 finding)."""
import unittest

import gpu_link_e2e as e


PROSE = ("A GPU renders a frame by taking vertices, transforming them, rasterizing triangles into fragments, shading each "
         "fragment with textures and lights, testing depth, blending, and finally writing the colours to a frame buffer "
         "that the display reads. Each stage runs in parallel across thousands of small cores. ") * 6


class DegenerateText(unittest.TestCase):
    def test_normal_prose_passes(self):
        self.assertIsNone(e.degenerate_text(PROSE))
        self.assertIsNone(e.degenerate_text("short"))
        self.assertIsNone(e.degenerate_text(""))

    def test_markdown_rules_and_tables_pass(self):
        text = PROSE + "\n" + "-" * 80 + "\n" + "=" * 60 + "\n| a | b |\n|---|---|\n" + "* " * 30 + "\n" + "." * 60
        self.assertIsNone(e.degenerate_text(text))

    def test_at_sign_run_from_the_rx580(self):
        self.assertIn("repeated character", e.degenerate_text(PROSE + "-@" + "@" * 400))

    def test_digit_run_from_the_rx580(self):
        self.assertIn("repeated character", e.degenerate_text(PROSE + "8" * 200))

    def test_looped_fragment_from_the_rx580(self):
        self.assertIn("loop", e.degenerate_text(PROSE + "asks8alion" * 120))

    def test_loop_that_starts_late_is_still_caught(self):
        self.assertIn("loop", e.degenerate_text(PROSE + "asks8alion" * 8))

    def test_wide_table_separator_is_not_a_loop(self):
        self.assertIsNone(e.degenerate_text(PROSE + "\n" + "|---" * 9 + "|\n"))

    def test_short_loop_is_not_judged(self):
        self.assertIsNone(e.degenerate_text("ha ha ha ha ha ha ha ha"))


if __name__ == "__main__":
    unittest.main()

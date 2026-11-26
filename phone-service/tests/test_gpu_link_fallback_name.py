# SPDX-License-Identifier: Apache-2.0
"""Without a companion lead_label the lead model is named for the paired computer, never a Mac as a PC."""

import os
import unittest
from unittest import mock

from opos import gpu_link


class FallbackNameTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(os.environ, {"OPOS_GPU_LINK_PC_DISPLAY": "M5 Pro PC=M5 Pro MacBook Pro"})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_generic_name_follows_a_mac(self):
        for generic in ("MacBook GPU", "Computer GPU", "computer gpu", "PC GPU", "Mac GPU"):
            self.assertEqual(gpu_link.fallback_model_name(generic, "M5 Pro PC"), "MacBook GPU")
            self.assertEqual(gpu_link.fallback_model_name(generic, "M4 Mac mini"), "Mac GPU")
            self.assertEqual(gpu_link.fallback_model_name(generic, "iMac"), "Mac GPU")

    def test_generic_name_is_neutral_otherwise(self):
        for label in ("RTX 5080 PC", None, "", "Macro box"):
            self.assertEqual(gpu_link.fallback_model_name("MacBook GPU", label), "Computer GPU")

    def test_real_model_name_is_kept(self):
        self.assertEqual(gpu_link.fallback_model_name("Nemotron Nano 9B", "M5 Pro PC"), "Nemotron Nano 9B")
        self.assertEqual(gpu_link.fallback_model_name("", "M5 Pro PC"), "")


if __name__ == "__main__":
    unittest.main()

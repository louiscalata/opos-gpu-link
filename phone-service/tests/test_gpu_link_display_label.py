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


if __name__ == "__main__":
    unittest.main()

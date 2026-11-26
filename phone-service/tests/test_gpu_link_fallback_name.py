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
            self.assertEqual(gpu_link.fallback_model_name(generic, "Louiss-MBP"), "MacBook GPU")
            self.assertEqual(gpu_link.fallback_model_name(generic, "MacBookPro18,3"), "MacBook GPU")
            self.assertEqual(gpu_link.fallback_model_name(generic, "Studio Macintosh"), "Mac GPU")

    def test_generic_name_is_neutral_otherwise(self):
        for label in ("RTX 5080 PC", None, "", "Macro box"):
            self.assertEqual(gpu_link.fallback_model_name("MacBook GPU", label), "Computer GPU")

    def test_real_model_name_is_kept(self):
        self.assertEqual(gpu_link.fallback_model_name("Nemotron Nano 9B", "M5 Pro PC"), "Nemotron Nano 9B")
        self.assertEqual(gpu_link.fallback_model_name("", "M5 Pro PC"), "")


class SnapshotFallbackTest(unittest.TestCase):
    """The app snapshot's lead model name follows the paired computer when no lead_label is known."""

    def setUp(self):
        try:
            from opos.ai_answers import AnswerStore
            from opos.gpu_link import LinkService
            from opos.store import Store
            from tests.gpu_link_fake_pc import Clock, FakePC, RandomBytes
        except ImportError as missing:
            self.skipTest(f"needs the host app: {missing}")
        import tempfile
        from pathlib import Path
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.enterContext(mock.patch.dict(os.environ, {
            "OPOS_STATE_DIR": str(root), "OPOS_APPS": "ai", "OPOS_MODEL_POOL": str(root / "missing.json"),
            "OPOS_GPU_LINK_PC_DISPLAY": "Test PC=Test MacBook Pro"}))
        store = Store(root / "state")
        model = root / "Original.gguf"
        model.write_bytes(b"fake model bytes")
        self.link = LinkService(AnswerStore(store), store, model, clock=Clock(), rand=RandomBytes())
        self.addCleanup(self.link.close)
        if self.link._hasher:
            self.link._hasher.join(2)
        self.link.set_model_name("MacBook GPU")
        self.FakePC = FakePC

    def pair(self, label):
        pc = self.FakePC(self.link, label=label)
        self.assertEqual(pc.enrol().status, 202)
        self.assertTrue(self.link.allow(pc.code))

    def test_unpaired_is_neutral(self):
        self.assertEqual(self.link.snapshot()["model"]["name"], "Computer GPU")

    def test_paired_mac_display_name(self):
        self.pair("Test PC")  # mapped to "Test MacBook Pro" for the screen
        self.assertEqual(self.link.snapshot()["model"]["name"], "MacBook GPU")

    def test_paired_non_mac_is_neutral(self):
        self.pair("RTX 5080 PC")
        self.assertEqual(self.link.snapshot()["model"]["name"], "Computer GPU")


if __name__ == "__main__":
    unittest.main()

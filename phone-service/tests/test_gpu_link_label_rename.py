# SPDX-License-Identifier: Apache-2.0
"""A companion that starts sending a new wire label keeps working on its existing pairing,
and the phone keeps the name it saved; the new name arrives only with a new pairing.
(No host app, no sockets: FakePC talks to LinkService in process.)"""

import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from opos.ai_answers import AnswerStore
from opos.gpu_link import LinkService
from opos.store import Store
from tests.gpu_link_fake_pc import Clock, FakePC, RandomBytes

OLD, NEW = "M5 Pro PC", "M5 Pro MacBook Pro"


def _refuse(*_args, **_kwargs):
    raise AssertionError("tests must not open a network connection")


class LabelRename(unittest.TestCase):
    def setUp(self):
        for target in ("connect", "connect_ex"):
            patcher = mock.patch.object(socket.socket, target, _refuse)
            patcher.start()
            self.addCleanup(patcher.stop)
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        model = root / "Original.gguf"
        model.write_bytes(b"fake model bytes")
        self.store = Store(root / "state")
        self.clock = Clock()
        self.link = LinkService(AnswerStore(self.store), self.store, model, clock=self.clock, rand=RandomBytes())
        self.addCleanup(self.link.close)
        if self.link._hasher:
            self.link._hasher.join(2)

    def pair(self, label):
        pc = FakePC(self.link, label=label)
        self.assertEqual(pc.hello().status, 200)
        self.assertEqual(pc.enrol().status, 202)
        self.assertTrue(self.link.allow(pc.code))
        self.assertEqual(pc.hello().status, 200)
        return pc

    def test_existing_pairing_survives_a_new_companion_label(self):
        pc = self.pair(OLD)
        pc.label = NEW  # what a restarted companion would send after the rename
        self.assertEqual(pc.hello().status, 200)
        self.assertEqual(pc.status("ready").status, 200)
        self.assertEqual(self.link.snapshot()["pc"]["label"], OLD)

    def test_new_label_needs_forget_and_a_new_allow(self):
        old = self.pair(OLD)
        renamed = FakePC(self.link, key=b"N" * 32, label=NEW)
        self.assertEqual(renamed.enrol().status, 409)  # the phone already trusts a computer
        self.assertTrue(self.link.forget(self.link.snapshot()["pc"]["id"]))
        self.assertIsNone(self.link.snapshot()["pc"])
        self.clock.advance(30)  # enrolment requests are rate limited; the companion retries
        self.assertEqual(renamed.enrol().status, 202)
        pending = self.link.snapshot()["pending"]
        self.assertEqual(pending["label"], NEW)
        self.assertTrue(self.link.allow(renamed.code))
        self.assertEqual(renamed.hello().status, 200)
        self.assertEqual(renamed.status("ready").status, 200)
        self.assertEqual(self.link.snapshot()["pc"]["label"], NEW)
        self.assertNotEqual(old.status("ready").status, 200)  # the old key no longer works


if __name__ == "__main__":
    unittest.main()

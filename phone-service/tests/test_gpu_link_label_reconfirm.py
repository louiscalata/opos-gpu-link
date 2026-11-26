# SPDX-License-Identifier: Apache-2.0
"""The lead label survives a v2 companion's unconfirmed first status (no host app needed)."""

import tempfile
import unittest
from pathlib import Path

from opos import gpu_link_proto as proto
from opos.ai_answers import AnswerStore
from opos.gpu_link import LinkService
from opos.store import Store
from tests.gpu_link_fake_pc import Clock, FakePC, RandomBytes

LABEL = "gemma-4-26B-it"


def status_body(**values):
    body = dict(state="ready", lease=None, copied=None, total=None,
                gpu=None, tokens=None, tps=None, error=None)
    body.update(values)
    return proto.dumps(body)


class LabelAcrossReconfirm(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        model = root / "Original.gguf"
        model.write_bytes(b"fake model bytes")
        self.link = LinkService(AnswerStore(Store(root / "state")), Store(root / "state"), model,
                                clock=Clock(), rand=RandomBytes())
        self.addCleanup(self.link.close)
        if self.link._hasher:
            self.link._hasher.join(2)
        self.pc = FakePC(self.link)
        self.assertEqual(self.pc.enrol().status, 202)
        self.assertTrue(self.link.allow(self.pc.code))
        self.assertEqual(self.pc.hello().status, 200)

    def request(self, body, *, version="2"):
        request = self.pc.prepare("POST", "/v1/status", body)
        if version is not None:
            request[2]["X-Link-Proto"] = version
        reply = self.pc.send(*request)
        return self.pc.verify(reply, "/v1/status", bytes.fromhex(request[2]["X-Link-Nonce"]))

    def label(self):
        return self.link.snapshot()["pc"].get("lead_label")

    def test_v2_first_status_after_hello_keeps_label(self):
        self.assertEqual(self.request(status_body(lead_label=LABEL)).status, 200)
        self.assertEqual(self.pc.hello().status, 200)  # replug or companion restart
        self.assertEqual(self.request(status_body()).status, 200)  # not yet confirmed
        self.assertEqual(self.label(), LABEL)
        self.assertEqual(self.request(status_body(lead_label=LABEL)).status, 200)
        self.assertEqual(self.label(), LABEL)

    def test_v2_explicit_null_still_clears(self):
        self.request(status_body(lead_label=LABEL))
        self.assertEqual(self.request(status_body(lead_label=None)).status, 200)
        self.assertIsNone(self.label())

    def test_legacy_companion_omission_still_clears(self):
        self.request(status_body(lead_label=LABEL))
        self.assertEqual(self.request(status_body(), version=None).status, 200)
        self.assertIsNone(self.label())


if __name__ == "__main__":
    unittest.main()

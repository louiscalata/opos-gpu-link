# SPDX-License-Identifier: Apache-2.0
"""Socket-free v1/v2 compatibility, authenticated labels and app snapshot paths."""

import json
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from opos import ai_answers, ai_page, assist, gpu_link_proto as proto
from opos.ai_answers import AnswerStore
from opos.gpu_link import LinkService
from opos.store import Store
from tests.ai_page_support import ROUTE
from tests.gpu_link_fake_pc import Clock, FakePC, RandomBytes


FALLBACK = "Small (fallback for Original)"


def status_body(**values):
    body = dict(state="ready", lease=None, copied=None, total=None,
                gpu=None, tokens=None, tps=None, error=None)
    body.update(values)
    return proto.dumps(body)


class LeadLabel(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.enterContext(mock.patch.dict(os.environ, {
            "OPOS_STATE_DIR": str(root), "OPOS_APPS": "ai",
            "OPOS_MODEL_POOL": str(root / "missing-pool.json")}))
        self.store = Store(root / "state")
        self.answers = AnswerStore(self.store)
        self.clock = Clock()
        model = root / "Original.gguf"
        model.write_bytes(b"fake model bytes")
        self.link = LinkService(self.answers, self.store, model, clock=self.clock, rand=RandomBytes())
        self.addCleanup(self.link.close)
        if self.link._hasher:
            self.link._hasher.join(2)
        self.pc = FakePC(self.link)
        self.assertEqual(self.pc.enrol().status, 202)
        self.assertTrue(self.link.allow(self.pc.code))
        self.assertEqual(self.pc.hello().status, 200)
        self.enterContext(mock.patch.object(ai_answers, "shared", return_value=self.answers))
        self.enterContext(mock.patch.object(ai_page, "gpu_link_server", SimpleNamespace(service=lambda: self.link)))
        self.enterContext(mock.patch.object(assist, "free_mb", return_value=2048))
        self.enterContext(mock.patch.object(assist, "local_route", return_value=ROUTE))
        self.state = ai_page.PageState()
        self.addCleanup(self.state.close)

    def request(self, body, *, version="2", target="/v1/status"):
        request = self.pc.prepare("POST", target, body)
        if version is not None:
            request[2]["X-Link-Proto"] = version
        reply = self.pc.send(*request)
        return self.pc.verify(reply, target, bytes.fromhex(request[2]["X-Link-Nonce"]))

    def test_current_version_and_legacy_reply_shapes_are_explicit(self):
        self.assertEqual((proto.LEGACY_PROTO, proto.PROTO), (1, 2))
        legacy_hello = self.pc.data(self.pc.hello())
        self.assertEqual(legacy_hello["proto"], 1)
        self.assertEqual(set(legacy_hello), {"proto", "label", "epoch"})
        old_reply = self.pc.data(self.pc.status())
        self.assertEqual(old_reply, {"cancel": None})
        self.assertIsNone(self.link.snapshot()["pc"].get("lead_label"))

    def test_opted_in_hello_and_signed_status_advertise_support(self):
        hello = self.pc.send("GET", "/v1/hello", {"X-Link-Proto": "2"})
        self.assertEqual(self.pc.data(hello)["proto"], 2)
        reply = self.request(status_body())
        self.assertEqual(reply.status, 200)
        self.assertEqual(self.pc.data(reply), {"cancel": None, "proto": 2})

    def test_new_label_uses_existing_gpu_model_text_path_without_file_identity_change(self):
        before = self.link.snapshot()["model"]
        self.assertEqual(self.request(status_body(lead_label=FALLBACK)).status, 200)
        snap = self.state.snapshot()
        self.assertEqual(snap["gpu"]["model"], FALLBACK)
        self.assertEqual(snap["gpu"]["link"]["pc"]["lead_label"], FALLBACK)
        self.assertEqual(snap["gpu"]["link"]["model"], before)
        self.assertNotEqual(snap["phone"]["model"], FALLBACK)

    def test_label_updates_running_answer_and_final_answer_keeps_actual_generator(self):
        self.pc.status("ready")
        answer = self.answers.ask("gpu", "Question")
        job = self.pc.data(self.pc.work())
        self.assertEqual(self.request(status_body(state="busy", lease=job["lease"],
                                                lead_label=FALLBACK)).status, 200)
        self.assertEqual(self.state.snapshot()["gpu"]["model"], FALLBACK)
        self.assertEqual(self.pc.text(job["lease"], 0, "answer", True, "stop").status, 200)
        self.assertEqual(self.answers.get(answer["id"])["model"], FALLBACK)
        self.assertEqual(self.state.snapshot()["gpu"]["lead_label"], FALLBACK)
        self.pc.status("ready")  # A legacy/restarted worker no longer reports fallback.
        self.assertEqual(self.state.snapshot()["gpu"]["model"], FALLBACK)

    def test_legacy_omission_and_explicit_null_clear_obsolete_label(self):
        for clear in (lambda: self.pc.status(),
                      lambda: self.request(status_body(lead_label=None))):
            with self.subTest(clear=clear):
                self.assertEqual(self.request(status_body(lead_label=FALLBACK)).status, 200)
                self.assertEqual(clear().status, 200)
                self.assertIsNone(self.link.snapshot()["pc"].get("lead_label"))
                self.assertEqual(self.state.snapshot()["gpu"]["model"], "Original")

    def test_label_is_volatile_across_forget_and_reenrol(self):
        self.request(status_body(lead_label=FALLBACK))
        self.assertTrue(self.link.forget())
        other = FakePC(self.link, key=b"Q" * 32, label="Other PC")
        self.assertEqual(other.enrol().status, 202)
        self.assertTrue(self.link.allow(other.code))
        self.assertEqual(other.hello().status, 200)
        self.assertIsNone(self.link.snapshot()["pc"].get("lead_label"))
        self.assertEqual(self.state.snapshot()["gpu"]["model"], "Original")

    def test_restart_does_not_persist_label_or_status(self):
        self.request(status_body(lead_label=FALLBACK))
        self.link.close()
        restarted = LinkService(self.answers, self.store, clock=self.clock, rand=RandomBytes())
        self.addCleanup(restarted.close)
        self.assertIsNone(restarted.snapshot()["pc"].get("lead_label"))
        self.assertIsNone(restarted.snapshot()["pc"]["state"])

    def test_other_pc_and_finished_history_are_not_relabelled(self):
        self.request(status_body(lead_label=FALLBACK))
        answer = self.answers.ask("gpu", "old question")
        self.answers.note(answer["id"], model="Previous model", where="Previous PC")
        self.assertEqual(self.state.snapshot()["gpu"]["model"], "Previous model")
        self.answers.fail(answer["id"], "stream_error")
        self.answers.note(answer["id"], where=self.pc.label)
        self.assertEqual(self.state.snapshot()["gpu"]["model"], "Previous model")
        self.assertEqual(self.state.snapshot()["gpu"]["lead_label"], FALLBACK)
        self.assertEqual(self.state.snapshot()["gpu"]["answer"]["model"], "Previous model")

    def test_unknown_version_does_not_enable_extended_shapes(self):
        for version in (None, "1", "3", "02", "2 "):
            with self.subTest(version=version):
                hello = self.pc.send("GET", "/v1/hello", {} if version is None else {"X-Link-Proto": version})
                self.assertEqual(self.pc.data(hello)["proto"], 1)
                reply = self.request(status_body(), version=version)
                self.assertEqual(self.pc.data(reply), {"cancel": None})
                self.assertEqual(self.request(status_body(lead_label=FALLBACK), version=version).status, 400)

    def test_extra_lane_cannot_change_lead_label(self):
        self.pc.advertise([{"id": "vendor/extra", "label": "Extra", "maker": "Maker", "gpu": None}])
        self.request(status_body(lead_label=FALLBACK))
        self.assertEqual(self.request(status_body(lead_label="Forged"),
                                     target="/v1/lanes/g1/status").status, 400)
        self.assertEqual(self.link.snapshot()["pc"]["lead_label"], FALLBACK)

    def test_invalid_status_does_not_change_last_accepted_label(self):
        self.request(status_body(lead_label=FALLBACK))
        for body in (status_body(lead_label=""), status_body(lead_label="A" * 65),
                     status_body(lead_label=7), status_body(lead_label="line\nbreak"),
                     status_body(lead_label="nonascii \u00e9"), status_body(lead_label=True),
                     status_body(lead_label="Forged", extra=True),
                     status_body(lead_label="Forged", lease="a" * 32)):
            with self.subTest(body=body):
                self.assertIn(self.request(body).status, (400, 404))
                self.assertEqual(self.link.snapshot()["pc"]["lead_label"], FALLBACK)

    def test_printable_ascii_and_exact_maximum_match_advertised_label_grammar(self):
        for value in ("A" * 64, "A / B (fallback for C)", " "):
            with self.subTest(value=value):
                self.assertEqual(self.request(status_body(lead_label=value)).status, 200)
                self.assertEqual(self.link.snapshot()["pc"]["lead_label"], value)

    def test_request_mac_covers_label_change_insertion_and_removal(self):
        self.request(status_body(lead_label=FALLBACK))
        original = status_body(lead_label=FALLBACK)
        for signed, mutated in ((original, status_body(lead_label="Forged")),
                                (original, status_body()),
                                (status_body(), original)):
            with self.subTest(mutated=mutated):
                method, target, headers, _ = self.pc.prepare("POST", "/v1/status", signed)
                headers["X-Link-Proto"] = "2"
                reply = self.pc.send(method, target, headers, mutated)
                self.assertEqual(reply.status, 401)
                self.assertEqual(self.link.snapshot()["pc"]["lead_label"], FALLBACK)

    def test_signed_reply_capability_cannot_be_inserted_or_stripped(self):
        for version in (None, "2"):
            body = status_body()
            method, target, headers, _ = self.pc.prepare("POST", "/v1/status", body)
            if version is not None:
                headers["X-Link-Proto"] = version
            reply = self.pc.send(method, target, headers, body)
            nonce = bytes.fromhex(headers["X-Link-Nonce"])
            self.pc.verify(reply, target, nonce)
            value = json.loads(reply.body)
            if version is None:
                value["proto"] = 2
            else:
                del value["proto"]
            with self.assertRaisesRegex(AssertionError, "reply signature"):
                self.pc.verify(replace(reply, body=proto.dumps(value)), target, nonce)


if __name__ == "__main__":
    unittest.main()

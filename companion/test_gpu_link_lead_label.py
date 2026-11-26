"""Real peer send/validation paths over an in-memory wire; no sockets/models."""

import importlib.util
import json
import queue
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gpu_link_worker as worker
import gpu_link_autosetup as setup
import gpu_link_health as health
import opos_gpu_link as link
import test_gpu_link_runtime_integration as integration

proto = worker.proto
KEY = bytes(range(32))
LABEL = "Small (fallback for Original)"
BASE = Path(__file__).resolve().parents[1] / "companion-r21-base"


def legacy_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    before = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = before
    return module


if not (BASE / "gpu_link_worker.py").is_file():
    raise unittest.SkipTest("legacy r21 wire copy (companion-r21-base) is not in the public tree")

old_proto = legacy_module("legacy_label_proto", BASE / "src/opos/gpu_link_proto.py")
old_worker = legacy_module("legacy_label_worker", BASE / "gpu_link_worker.py")
old_worker.proto = old_proto


class Phone:
    """Use each version's real strict parser, greeting, signing and reply writer."""

    def __init__(self, version):
        self.version = version
        self.proto = old_proto if version == 1 else proto
        self.epoch = b"E" * 16
        self.requests = []
        self.stored_label = None
        self.edit_request = self.edit_reply = None
        self.hello_version = None
        self.strip_opt_in = False
        self.legacy_reply = False

    def handle(self, method, target, raw, headers):
        headers = dict(headers)
        self.requests.append((method, target, raw, headers))
        if self.strip_opt_in:
            headers.pop("X-Link-Proto", None)
        opt_in = self.version == 2 and headers.get("X-Link-Proto") == "2"
        if target == "/v1/hello":
            version = self.hello_version or (2 if opt_in else 1)
            body = (proto.hello_body("Phone", self.epoch, proto_version=version)
                    if version == 2 else old_proto.hello_body("Phone", self.epoch))
            return Response(200, body, [])
        if self.edit_request:
            raw = self.edit_request(raw)
        nonce = bytes.fromhex(headers["X-Link-Nonce"])
        expected = self.proto.request_mac(KEY, self.epoch, method, target, "", nonce, raw)
        if not self.proto.same_mac(headers.get("X-Link-Mac"), expected):
            return Response(401, b"", [])
        try:
            payload = self.proto.parse_status(raw)
            if "lead_label" in payload and (not opt_in or target != "/v1/status"):
                raise proto.ProtoError("request")
        except (proto.ProtoError, old_proto.ProtoError):
            status, body = 400, self.proto.error_reply("request")
        else:
            self.stored_label = payload.get("lead_label")
            status = 200
            body = (proto.status_reply(None, proto_version=2) if opt_in and not self.legacy_reply
                    else old_proto.status_reply(None))
        mac = self.proto.reply_mac(KEY, nonce, status, "", body)
        if self.edit_reply:
            body = self.edit_reply(body)
        return Response(status, body, [("X-Link-Mac", mac)])


class Response:
    def __init__(self, status, body, fields):
        self.status, self.body, self.fields = status, body, fields
        self.length = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def getheaders(self):
        return self.fields

    def getheader(self, name, default=None):
        return next((v for k, v in self.fields if k.lower() == name.lower()), default)

    def read(self, _size):
        return self.body


class Connection:
    def __init__(self, phone):
        self.phone = phone

    def request(self, method, target, body=b"", headers=None):
        self.response = self.phone.handle(method, target, body, headers)

    def getresponse(self):
        return self.response

    def close(self):
        pass


class LabelWireTests(unittest.TestCase):
    def connect(self, phone_version=2, old=False):
        phone = Phone(phone_version)
        self.addCleanup(patch.stopall)
        patch.object(worker.http.client, "HTTPConnection", side_effect=lambda *_a, **_k: Connection(phone)).start()
        pc = (old_worker if old else worker).PC("127.0.0.1:38641", KEY)
        return phone, pc

    def test_new_companion_old_phone_never_receives_new_field(self):
        phone, pc = self.connect(1)
        pc.lead_label = LABEL
        pc.hello()
        for _ in range(3):
            self.assertEqual(pc.status(), (200, {"cancel": None}))
        posts = [json.loads(raw) for method, _, raw, _ in phone.requests if method == "POST"]
        self.assertEqual(len(posts), 3)
        self.assertTrue(all("lead_label" not in body for body in posts))
        self.assertIsNone(pc.label_epoch)

    def test_actual_old_companion_new_phone_preserves_strict_replies(self):
        phone, pc = self.connect(old=True)
        pc.hello()
        self.assertEqual(pc.status(), (200, {"cancel": None}))
        self.assertEqual(pc.status(), (200, {"cancel": None}))
        self.assertIsNone(phone.stored_label)
        self.assertTrue(all("X-Link-Proto" not in headers for _, _, _, headers in phone.requests))

    def test_new_peers_confirm_before_sending_label_and_null_clears(self):
        phone, pc = self.connect()
        pc.lead_label = LABEL
        pc.hello()
        self.assertIsNone(pc.label_epoch)
        pc.status()
        self.assertNotIn("lead_label", json.loads(phone.requests[-1][2]))
        pc.status()
        self.assertEqual(phone.stored_label, LABEL)
        pc.lead_label = None
        pc.status()
        self.assertIn("lead_label", json.loads(phone.requests[-1][2]))
        self.assertIsNone(phone.stored_label)

    def test_legacy_status_bytes_are_unchanged_before_confirmation(self):
        phone, pc = self.connect(1)
        pc.hello()
        pc.status()
        new_body = phone.requests[-1][2]
        phone, old = self.connect(1, old=True)
        old.hello()
        old.status()
        self.assertEqual(new_body, phone.requests[-1][2])

    def test_unsigned_hello_cannot_enable_capability(self):
        phone, pc = self.connect(1)
        phone.hello_version = 2  # An unauthenticated forged greeting.
        pc.lead_label = LABEL
        pc.hello()
        pc.status()
        pc.status()
        self.assertIsNone(phone.stored_label)
        self.assertNotIn("lead_label", json.loads(phone.requests[-1][2]))

    def test_forged_or_stripped_confirmation_fails_mac_without_enabling(self):
        for version in (1, 2):
            with self.subTest(version=version):
                phone, pc = self.connect(version)
                pc.hello()
                phone.edit_reply = lambda raw: proto.dumps({"cancel": None, "proto": 2}) if version == 1 else b'{"cancel":null}'
                with self.assertRaisesRegex(worker.ToolError, "signature"):
                    pc.status()
                self.assertIsNone(pc.label_epoch)

    def test_tampered_or_stripped_label_fails_request_mac(self):
        for edit in (lambda body: dict(body, lead_label="Forged"),
                     lambda body: {k: v for k, v in body.items() if k != "lead_label"}):
            with self.subTest(edit=edit):
                phone, pc = self.connect()
                pc.hello()
                pc.status()
                pc.lead_label = LABEL
                phone.edit_request = lambda raw: proto.dumps(edit(json.loads(raw)))
                with self.assertRaises(worker.RejectedError):
                    pc.status()
                self.assertIsNone(phone.stored_label)

    def test_stripped_opt_in_after_confirmation_stops(self):
        phone, pc = self.connect()
        pc.hello()
        pc.status()
        phone.strip_opt_in = True
        with self.assertRaisesRegex(worker.ToolError, "status refused"):
            worker.StandIn(pc, emit=lambda _line: None)._status()
        self.assertIsNone(phone.stored_label)

    def test_signed_downgrade_after_confirmation_stops(self):
        phone, pc = self.connect()
        pc.hello()
        pc.status()
        phone.legacy_reply = True
        with self.assertRaisesRegex(worker.ToolError, "confirmation disappeared"):
            pc.status()
        self.assertIsNone(pc.label_epoch)

    def test_epoch_rejection_rebuilds_legacy_status_before_reconfirmation(self):
        phone, pc = self.connect()
        pc.hello()
        pc.status()
        pc.lead_label = LABEL
        phone.epoch = b"N" * 16
        reactor = worker.StandIn(pc, emit=lambda _line: None)
        self.assertEqual(reactor._send_status()[0], 200)
        self.assertIn("lead_label", json.loads(phone.requests[-3][2]))
        self.assertEqual(phone.requests[-2][1], "/v1/hello")
        self.assertNotIn("lead_label", json.loads(phone.requests[-1][2]))
        pc.status()
        self.assertEqual(phone.stored_label, LABEL)

    def test_same_epoch_reconnect_requires_new_confirmation(self):
        phone, pc = self.connect()
        pc.hello()
        pc.status()
        pc.lead_label = LABEL
        pc.hello()
        pc.status()
        self.assertNotIn("lead_label", json.loads(phone.requests[-1][2]))

    def test_extra_lane_never_sends_lead_label(self):
        phone, _ = self.connect()
        pc = worker.LanePC("127.0.0.1:38641", KEY, "PC", "g1")
        pc.hello()
        pc.label_epoch, pc.lead_label = pc.epoch, LABEL
        pc.status()
        self.assertEqual(phone.requests[-1][1], "/v1/lanes/g1/status")
        self.assertNotIn("lead_label", json.loads(phone.requests[-1][2]))

    def test_label_parser_matches_advertised_grammar_and_keeps_keys_strict(self):
        payload = dict(state="ready", lease=None, copied=None, total=None, gpu=None,
                       tokens=None, tps=None, error=None)
        self.assertEqual(proto.parse_status(proto.dumps(payload)), payload)
        for value in (None, LABEL, "x" * 64, "Model.2 / Q4_K (fallback)"):
            self.assertEqual(proto.parse_status(proto.dumps(dict(payload, lead_label=value)))["lead_label"], value)
        for value in ("", "x" * 65, "line\nfeed", "tab\t", "\x7f", "é", 7, True, [], {}):
            with self.subTest(value=value), self.assertRaises(proto.ProtoError):
                proto.parse_status(proto.dumps(dict(payload, lead_label=value)))
        with self.assertRaises(proto.ProtoError):
            proto.parse_status(proto.dumps(dict(payload, lead_label=LABEL, extra="unknown")))

    def test_invalid_label_refuses_before_sending(self):
        phone, pc = self.connect()
        pc.hello()
        pc.status()
        pc.lead_label = "bad\nlabel"
        count = len(phone.requests)
        with self.assertRaisesRegex(worker.ToolError, "invalid lead model label"):
            pc.status()
        self.assertEqual(len(phone.requests), count)

    def test_hello_and_status_capabilities_reject_wrong_types_and_unknown_keys(self):
        for version in (0, 3, True, "2", None):
            for encode in (lambda: proto.hello_body("Phone", b"E" * 16, proto_version=version),
                           lambda: proto.status_reply(None, proto_version=version)):
                with self.subTest(version=version), self.assertRaises(proto.ProtoError):
                    encode()
        for payload in ({"cancel": None, "proto": True}, {"cancel": None, "proto": 3},
                        {"cancel": None, "proto": 2, "unknown": 1}):
            with self.assertRaises(worker.RetryError):
                worker.checked_reply("/v1/status", 200, proto.dumps(payload))


class RuntimeLabelTests(unittest.TestCase):
    setUp = integration.RuntimeFixture.setUp

    def start_worker(self, pc):
        app = link.Companion.__new__(link.Companion)
        app.running, app.events = True, queue.SimpleQueue()
        app.args = SimpleNamespace(model=self.alias, runtime=self.rt, extra_models=[])
        with patch.object(link, "StandIn"):
            app._start_worker(pc)
            app.worker.join(2)
        self.assertFalse(app.worker.is_alive())

    def test_successful_policy_swap_updates_live_getter_without_extra_lanes(self):
        pc = worker.PC("127.0.0.1:38641", KEY)
        self.start_worker(pc)
        self.assertIsNone(pc.lead_label_source())
        replacement = integration.process(self.argv, 65002)
        with patch.object(setup.subprocess, "Popen", return_value=replacement), \
                patch.object(setup, "wait_healthy", return_value=True), \
                patch.object(health, "port_available", return_value=True):
            for lease in ("first", "second"):
                self.rt.record_failure(self.alias, dict(self.job, lease=lease), "garbled")
            self.rt.fallback_threads[-1].join(2)
        self.assertEqual(pc.lead_label_source(), LABEL)
        self.start_worker(pc)  # Reconnect retains the show-lifetime replacement label.
        self.assertEqual(pc.lead_label_source(), LABEL)

    def test_failed_load_never_publishes_fallback_label(self):
        pc = worker.PC("127.0.0.1:38641", KEY)
        self.start_worker(pc)
        replacement = integration.process(self.argv, 65002)
        def not_ready(*_args, **_kwargs):
            self.assertIsNone(pc.lead_label_source())
            return False
        with patch.object(setup.subprocess, "Popen", return_value=replacement), \
                patch.object(setup, "wait_healthy", side_effect=not_ready), \
                patch.object(health, "port_available", return_value=True):
            self.rt._fallback(self.alias, self.job["question"], self.candidate)
        self.assertIsNone(pc.lead_label_source())


if __name__ == "__main__":
    unittest.main()

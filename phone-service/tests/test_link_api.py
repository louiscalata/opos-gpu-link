# SPDX-License-Identifier: Apache-2.0
"""The standalone app API: the token page, the snapshot, actions, HTTP checks and the phone lane."""

from __future__ import annotations

import contextlib
import hashlib
import http.client
import io
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_link  # noqa: E402
from opos import ai_answers, gpu_link_server, link_api  # noqa: E402
from opos.ai_answers import AnswerStore  # noqa: E402
from opos.gpu_link import LinkService  # noqa: E402
from opos.store import Store  # noqa: E402
from tests.gpu_link_fake_pc import Clock, FakePC, RandomBytes  # noqa: E402

TOKEN_RE = re.compile(r'<meta\s+name="opos-token"\s+content="([A-Za-z0-9_-]+)"')  # as AiClient.java


def wait_for(check, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition never became true")


class FakeLlama:
    """A loopback OpenAI-compatible server that streams fixed pieces."""

    def __init__(self, pieces=("Blue ", "light ", "scatters."), hold=None, finish="stop", done=True,
                 status=200, content_type="text/event-stream"):
        outer = self
        self.pieces, self.hold, self.requests = pieces, hold, []
        self.finish, self.done, self.status, self.content_type = finish, done, status, content_type

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                try:
                    self.answer()
                except (BrokenPipeError, ConnectionResetError):
                    pass  # the phone cancelled and closed the stream

            def answer(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append((self.path, body))
                self.send_response(outer.status)
                self.send_header("Content-Type", outer.content_type)
                self.end_headers()
                for piece in outer.pieces:
                    event = {"choices": [{"delta": {"content": piece}, "finish_reason": None}]}
                    self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    self.wfile.flush()
                    if outer.hold is not None:
                        outer.hold.wait(5)
                if outer.finish is not None:
                    done = {"choices": [{"delta": {}, "finish_reason": outer.finish}]}
                    self.wfile.write(f"data: {json.dumps(done)}\n\n".encode())
                if outer.done:
                    self.wfile.write(b"data: [DONE]\n\n")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def close(self):
        if self.hold is not None:
            self.hold.set()
        self.server.shutdown()
        self.server.server_close()


class Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.store = Store(root / "state")
        self.answers = AnswerStore(self.store)
        self.model = root / "test-model.gguf"
        self.model.write_bytes(b"model bytes\x00\xff" * 16)
        self.sha = hashlib.sha256(self.model.read_bytes()).hexdigest()
        self.clock = Clock()
        self.link = LinkService(self.answers, self.store, self.model, clock=self.clock, rand=RandomBytes())
        self.addCleanup(self.link.close)
        if self.link._hasher:
            self.link._hasher.join(2)
        self.pc = FakePC(self.link)
        self.assertEqual(self.pc.hello().status, 200)
        self.use_link = True

    def api(self, phone=None):
        api = link_api.LinkApi(phone, answers=lambda: self.answers,
                               link=lambda: self.link if self.use_link else None)
        self.addCleanup(api.close)
        return api

    def enrolled(self, ready=True):
        self.assertEqual(self.pc.enrol().status, 202)
        self.assertTrue(self.link.allow(self.pc.code))
        self.assertEqual(self.pc.hello().status, 200)
        if ready:
            self.assertEqual(self.pc.status("ready").status, 200)


class SnapshotTests(Base):
    def test_shape_matches_what_the_app_reads(self):
        data = self.api().snapshot()
        self.assertEqual(set(data), {"boot", "rev", "phone", "gpu", "models", "presets"})
        self.assertEqual(set(data["phone"]), {"model", "where", "ready", "answer", "live_speed"})
        self.assertFalse(data["phone"]["ready"])
        self.assertEqual(data["phone"]["where"], "on this phone")
        self.assertEqual(data["gpu"]["where"], "on the PC's GPU")
        self.assertIsNone(data["gpu"]["link"]["pc"])
        self.assertEqual(data["gpu"]["link"]["enrol"], "open")
        self.assertEqual([item["label"] for item in data["presets"]],
                         ["Why the sky is blue", "A welcoming garden", "A long guide (20 sections)"])
        self.assertEqual(data["models"], [])

    def test_rev_moves_only_on_change(self):
        api = self.api()
        first = api.snapshot()["rev"]
        self.assertEqual(api.snapshot()["rev"], first)
        self.assertEqual(self.pc.enrol().status, 202)
        self.assertEqual(api.snapshot()["rev"], first + 1)
        self.assertEqual(api.snapshot()["gpu"]["link"]["pending"]["code"], self.pc.code)

    def test_gpu_ready_needs_a_live_ready_pc(self):
        api = self.api()
        self.enrolled(ready=False)
        self.assertFalse(api.snapshot()["gpu"]["ready"])
        self.assertEqual(self.pc.status("ready").status, 200)
        data = api.snapshot()
        self.assertTrue(data["gpu"]["ready"])
        self.assertEqual(data["gpu"]["link"]["pc"]["label"], "Test PC")

    def test_advertised_pc_models_become_pc_lanes(self):
        api = self.api()
        self.enrolled()
        model = {"id": "big-model", "label": "Big model", "maker": "Lab", "gpu": None}
        self.assertEqual(self.pc.advertise([model]).status, 200)
        self.assertEqual(self.pc.lane_status("g1", "ready").status, 200)
        lanes = api.snapshot()["models"]
        self.assertEqual([(item["pane"], item["kind"], item["label"], item["ready"]) for item in lanes],
                         [("g1", "pc", "Big model", True)])

    def test_lfm2_is_a_visible_baseline_without_changing_advertisement(self):
        api = self.api()
        self.enrolled()
        source = {"id": "lfm2-1.2b", "label": "LFM2 1.2B", "maker": "Liquid AI", "gpu": None}
        self.assertEqual(self.pc.advertise([source]).status, 200)
        lane = api.snapshot()["models"][0]
        self.assertEqual((lane["label"], lane["maker"], lane["model"]),
                         ("LFM2 1.2B (baseline)", "Liquid AI", "LFM2 1.2B (baseline)"))
        self.assertEqual(self.link._advertised["g1"]["label"], "LFM2 1.2B")
        self.assertEqual(source["label"], "LFM2 1.2B")

    def test_saved_mac_answer_uses_display_label_in_every_view(self):
        api = self.api()
        answer = self.answers.ask("gpu", "Question", model="Nemotron-3.5-Bolt-E4B")
        self.answers.note(answer["id"], where="M5 Pro PC")
        with mock.patch.dict(os.environ, {"OPOS_GPU_LINK_PC_DISPLAY": "M5 Pro PC=M5 Pro MacBook Pro"}):
            gpu = api.snapshot()["gpu"]
        self.assertEqual(gpu["where"], "M5 Pro MacBook Pro")
        self.assertEqual(gpu["answer"]["where"], "M5 Pro MacBook Pro")
        self.assertEqual(gpu["answer"]["model"], "Nemotron 3.5 Bolt")
        self.assertEqual(self.answers.get(answer["id"])["where"], "M5 Pro PC")

    def test_saved_extra_answer_keeps_maker_and_mac_name(self):
        api = self.api()
        answer = self.answers.ask("g1", "Question", model="LFM2-1.2B")
        self.answers.note(answer["id"], where="M5 Pro PC")
        with mock.patch.dict(os.environ, {"OPOS_GPU_LINK_PC_DISPLAY": "M5 Pro PC=M5 Pro MacBook Pro"}):
            lane = api.snapshot()["models"][0]
        self.assertEqual((lane["label"], lane["maker"], lane["answer"]["where"]),
                         ("LFM2 1.2B (baseline)", "Liquid AI", "M5 Pro MacBook Pro"))
        self.assertEqual(self.answers.get(answer["id"])["model"], "LFM2-1.2B")


class ActionTests(Base):
    def test_ask_gpu_runs_through_the_pc_and_finishes(self):
        api = self.api()
        self.enrolled()
        status, data = api.post({"action": "ask", "question": "Why is the sky blue?", "panes": ["phone", "gpu"]})
        self.assertEqual(status, 200, data)
        self.assertIsNone(data["phone"]["answer"])  # no phone model: the phone pane is skipped
        self.assertEqual(data["gpu"]["answer"]["state"], "waiting")
        work = self.pc.data(self.pc.work())
        self.assertEqual(self.pc.text(work["lease"], 0, "Rayleigh scattering.", done=True, finish="stop").status, 200)
        answer = api.snapshot()["gpu"]["answer"]
        self.assertEqual((answer["state"], answer["text"]), ("done", "Rayleigh scattering."))

    def test_refusals_use_the_app_sentences(self):
        api = self.api()
        cases = [
            ({"action": "nope"}, "Choose an AI mode action."),
            ({"action": "ask", "question": "  ", "panes": ["gpu"]}, "Enter a question."),
            ({"action": "ask", "question": "x" * 4097, "panes": ["gpu"]}, "Keep the question to 4,096 bytes or fewer."),
            ({"action": "ask", "question": "Hi", "panes": ["gpu", "gpu"]}, "Choose each pane once."),
            ({"action": "ask", "question": "Hi", "panes": ["zz"]}, "Choose an available phone, GPU, or model pane."),
            ({"action": "ask", "question": "Hi", "panes": ["m1"]}, "No selected model is available."),
            ({"action": "ask", "question": "Hi", "panes": ["g1"]}, "No selected model is available."),
            ({"action": "cancel", "id": "missing"}, "That answer was not found."),
            ({"action": "retry", "pane": "gpu"}, "There is no answer to retry."),
            ({"action": "allow", "code": "000000"}, "That request is no longer waiting."),
            ({"action": "deny", "code": "000000"}, "That request is no longer waiting."),
            ({"action": "forget"}, "There is no computer request to change."),
        ]
        for body, error in cases:
            with self.subTest(body=body):
                self.assertEqual(api.post(body), (400, {"error": error}))
        self.assertEqual(api.post([]), (400, {"error": "Choose an AI mode action."}))
        self.use_link = False
        self.assertEqual(api.post({"action": "ask", "question": "Hi", "panes": ["gpu"]}),
                         (400, {"error": "GPU Link is off."}))
        self.assertEqual(api.post({"action": "reopen"}), (400, {"error": "GPU Link is off."}))

    def test_second_ask_waits_and_cancel_ends_it(self):
        api = self.api()
        self.enrolled()
        _, data = api.post({"action": "ask", "question": "One", "panes": ["gpu"]})
        ident = data["gpu"]["answer"]["id"]
        self.assertEqual(api.post({"action": "ask", "question": "Two", "panes": ["gpu"]}),
                         (400, {"error": "Wait for this answer, or stop it."}))
        status, data = api.post({"action": "cancel", "id": ident})
        self.assertEqual((status, data["gpu"]["answer"]["state"]), (200, "cancelled"))
        self.assertEqual(api.post({"action": "cancel", "id": ident}), (400, {"error": "That answer has already ended."}))

    def test_retry_needs_the_seen_id_and_asks_again(self):
        api = self.api()
        self.enrolled()
        _, data = api.post({"action": "ask", "question": "Again?", "panes": ["gpu"]})
        ident = data["gpu"]["answer"]["id"]
        self.assertEqual(api.post({"action": "retry", "pane": "gpu"}), (400, {"error": "Name the answer to retry."}))
        self.assertEqual(api.post({"action": "retry", "pane": "gpu", "id": "other"}),
                         (400, {"error": "That answer has already been replaced."}))
        status, data = api.post({"action": "retry", "pane": "gpu", "id": ident})
        self.assertEqual(status, 200)
        self.assertNotEqual(data["gpu"]["answer"]["id"], ident)
        self.assertEqual(data["gpu"]["answer"]["question"], "Again?")
        self.assertEqual(self.answers.get(ident)["state"], "cancelled")

    def test_safe_retry_on_gpu_still_replaces_the_answer(self):
        api = self.api()
        self.enrolled()
        _, data = api.post({"action": "ask", "question": "Again?", "panes": ["gpu"]})
        ident = data["gpu"]["answer"]["id"]

        status, data = api.post({"action": "retry", "pane": "gpu", "id": ident, "safe": 1})

        self.assertEqual(status, 200)
        self.assertNotEqual(data["gpu"]["answer"]["id"], ident)
        self.assertEqual(data["gpu"]["answer"]["question"], "Again?")
        self.assertEqual(self.answers.get(ident)["state"], "cancelled")

    def test_allow_deny_forget_and_reopen(self):
        api = self.api()
        self.assertEqual(self.pc.enrol().status, 202)
        status, data = api.post({"action": "allow", "code": self.pc.code})
        self.assertEqual((status, data["gpu"]["link"]["pc"]["label"]), (200, "Test PC"))
        self.assertEqual(api.post({"action": "forget", "expect": "wrong"}),
                         (400, {"error": "That is a different computer now."}))
        status, data = api.post({"action": "forget", "expect": data["gpu"]["link"]["pc"]["id"]})
        self.assertEqual((status, data["gpu"]["link"]["pc"]), (200, None))
        for _ in range(3):
            self.clock.advance(120)
            self.assertEqual(self.pc.enrol().status, 202)
            self.assertEqual(api.post({"action": "deny", "code": self.pc.code})[0], 200)
        self.assertEqual(api.snapshot()["gpu"]["link"]["enrol"], "closed")
        status, data = api.post({"action": "reopen"})
        self.assertEqual((status, data["gpu"]["link"]["enrol"]), (200, "open"))

    def test_storage_failure_is_a_500(self):
        api = self.api()
        self.enrolled()
        with mock.patch.object(self.answers, "ask", side_effect=OSError("disk")):
            self.assertEqual(api.post({"action": "ask", "question": "Hi", "panes": ["gpu"]}),
                             (500, {"error": "The phone could not save the answer."}))


class PhoneLaneTests(Base):
    def test_phone_model_url_must_be_loopback_http(self):
        for url in ("https://127.0.0.1:8080/v1", "http://example.com:8080/v1", "http://127.0.0.1/v1",
                    "http://user:pw@127.0.0.1:8080/v1", "http://203.0.113.5:8080/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                link_api.PhoneModel(url, "m")
        for url in ("http://127.0.0.1:8080/v1?", "http://127.0.0.1:8080/v1#", "http://127.0.0.1:99999/v1"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                link_api.PhoneModel(url, "m")
        with self.assertRaises(ValueError):
            link_api.PhoneModel("http://127.0.0.1:8080/v1", "   ")
        self.assertEqual(link_api.PhoneModel("http://127.0.0.1:8080/v1/", "m").url,
                         "http://127.0.0.1:8080/v1/chat/completions")

    def test_phone_lane_streams_into_the_store(self):
        llama = FakeLlama()
        self.addCleanup(llama.close)
        api = self.api(link_api.PhoneModel(llama.url, "tiny.gguf", "Tiny"))
        self.assertTrue(api.snapshot()["phone"]["ready"])
        status, data = api.post({"action": "ask", "question": "Sky?", "panes": ["phone"]})
        self.assertEqual(status, 200, data)
        ident = data["phone"]["answer"]["id"]
        wait_for(lambda: self.answers.get(ident)["state"] == "done")
        phone = api.snapshot()["phone"]
        self.assertEqual((phone["answer"]["text"], phone["model"], phone["where"]),
                         ("Blue light scatters.", "Tiny", "on this phone"))
        path, body = llama.requests[0]
        self.assertEqual((path, body["model"], body["stream"], body["messages"][-1]["content"]),
                         ("/v1/chat/completions", "tiny.gguf", True, "Sky?"))

    def test_safe_retry_changes_only_the_phone_completion_payload(self):
        llama = FakeLlama()
        self.addCleanup(llama.close)
        api = self.api(link_api.PhoneModel(llama.url, "tiny.gguf"))
        status, data = api.post({"action": "ask", "question": "Sky?", "panes": ["phone"]})
        self.assertEqual(status, 200)
        ident = data["phone"]["answer"]["id"]
        wait_for(lambda: self.answers.get(ident)["state"] == "done")
        normal_body = {"model": "tiny.gguf", "stream": True, "max_tokens": 4096,
                       "messages": [{"role": "user", "content": "Sky?"}]}
        self.assertEqual(llama.requests[-1][1], normal_body)

        with mock.patch.object(link_api.secrets, "randbits", side_effect=(101, 202)):
            for seed in (101, 202):
                status, data = api.post({"action": "retry", "pane": "phone", "id": ident, "safe": 1})
                self.assertEqual(status, 200)
                ident = data["phone"]["answer"]["id"]
                wait_for(lambda: self.answers.get(ident)["state"] == "done")
                self.assertEqual(llama.requests[-1][1],
                                 {**normal_body, "seed": seed, "temperature": 0.1, "repeat_penalty": 1.1})

        for safe in (None, "1"):
            body = {"action": "retry", "pane": "phone", "id": ident}
            if safe is not None:
                body["safe"] = safe
            status, data = api.post(body)
            self.assertEqual(status, 200)
            ident = data["phone"]["answer"]["id"]
            wait_for(lambda: self.answers.get(ident)["state"] == "done")
            self.assertEqual(llama.requests[-1][1], normal_body)

    def test_cancel_stops_a_phone_answer(self):
        llama = FakeLlama(hold=threading.Event())
        self.addCleanup(llama.close)
        api = self.api(link_api.PhoneModel(llama.url, "tiny.gguf"))
        _, data = api.post({"action": "ask", "question": "Long?", "panes": ["phone"]})
        ident = data["phone"]["answer"]["id"]
        wait_for(lambda: self.answers.get(ident)["state"] in ("loading", "answering"))
        job = api.workers[ident]
        status, data = api.post({"action": "cancel", "id": ident})
        self.assertEqual((status, data["phone"]["answer"]["state"]), (200, "cancelled"))
        # Cancel closes the connection, so the blocked read wakes without the server's help.
        job.thread.join(2)
        self.assertFalse(job.thread.is_alive())
        self.assertEqual(self.answers.get(ident)["state"], "cancelled")

    def phone_answer(self, llama):
        self.addCleanup(llama.close)
        api = self.api(link_api.PhoneModel(llama.url, "tiny.gguf"))
        _, data = api.post({"action": "ask", "question": "Hi", "panes": ["phone"]})
        ident = data["phone"]["answer"]["id"]
        wait_for(lambda: self.answers.get(ident)["state"] in ai_answers.FINAL)
        return api, self.answers.get(ident)

    def test_stream_endings(self):
        cases = [
            (dict(finish="length"), ("done", "length", None)),
            (dict(finish="tool_calls"), ("done", "stop", None)),
            (dict(finish=None, done=True), ("done", "stop", None)),
            (dict(finish=None, done=False), ("failed", None, "stream_error")),  # cut off mid-answer
            (dict(status=500), ("failed", None, "stream_error")),
            (dict(content_type="application/json"), ("failed", None, "stream_error")),
            (dict(pieces=("x" * 5000,) * 3), ("failed", None, "too_long")),
        ]
        for kwargs, expected in cases:
            with self.subTest(**{k: str(v)[:20] for k, v in kwargs.items()}):
                api, answer = self.phone_answer(FakeLlama(**kwargs))
                self.assertEqual((answer["state"], answer["finish"], answer["error"]), expected)
                self.assertTrue(api.snapshot()["phone"]["ready"])  # only an unreachable server clears ready

    def test_multibyte_text_survives_piece_boundaries(self):
        _, answer = self.phone_answer(FakeLlama(pieces=("caf", "é ", "🌍", "\r\nok")))
        self.assertEqual((answer["state"], answer["text"]), ("done", "café 🌍\nok"))

    def test_unreachable_phone_model_fails_with_a_code(self):
        llama = FakeLlama()
        url = llama.url
        llama.close()
        api = self.api(link_api.PhoneModel(url, "tiny.gguf"))
        _, data = api.post({"action": "ask", "question": "Hi", "panes": ["phone"]})
        ident = data["phone"]["answer"]["id"]
        wait_for(lambda: self.answers.get(ident)["state"] == "failed")
        self.assertEqual(self.answers.get(ident)["error"], "no_model")
        self.assertFalse(api.snapshot()["phone"]["ready"])


class HttpTests(Base):
    """Drive the server exactly as AiClient.java does."""

    def setUp(self):
        super().setUp()
        self.server = link_api.AppServer(self.api(), port=0)
        self.server.start()
        self.addCleanup(self.server.stop)
        self.port = self.server.port

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request(method, path, body, headers or {})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def token(self):
        status, headers, body = self.request("GET", "/ai", headers={"Accept": "text/html"})
        self.assertEqual(status, 200)
        self.assertTrue(headers["Content-Type"].startswith("text/html"))
        return TOKEN_RE.search(body.decode()).group(1)

    def post(self, data, token=None, **overrides):
        body = json.dumps(data).encode()
        headers = {"Content-Type": "application/json; charset=utf-8", "Origin": f"http://127.0.0.1:{self.port}",
                   "X-OPOS-Token": token or self.token()}
        headers.update(overrides)
        return self.request("POST", "/api/ai", body, headers)

    def test_token_page_and_snapshot(self):
        token = self.token()
        status, headers, body = self.request("GET", "/api/ai", headers={"X-OPOS-Token": token})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("gpu", json.loads(body))

    def test_missing_or_wrong_token_is_403(self):
        self.assertEqual(self.request("GET", "/api/ai")[0], 403)
        self.assertEqual(self.request("GET", "/api/ai", headers={"X-OPOS-Token": "wrong"})[0], 403)
        status, _, body = self.post({"action": "reopen"}, token="wrong")
        self.assertEqual((status, json.loads(body)), (403, {"error": "forbidden"}))

    def test_post_checks_origin_type_host_and_size(self):
        token = self.token()
        self.assertEqual(self.post({"action": "reopen"}, token, Origin="http://evil.example")[0], 403)
        self.assertEqual(self.post({"action": "reopen"}, token, **{"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.post({"action": "reopen"}, token, Host="evil.example")[0], 403)
        status, _, body = self.post({"action": "ask", "question": "x" * link_api.BODY_LIMIT}, token)
        self.assertEqual((status, json.loads(body)), (413, {"error": "body too large"}))
        self.assertEqual(self.request("GET", "/ai", headers={"Host": "evil.example"})[0], 403)
        self.assertEqual(self.request("GET", "/other")[0], 404)
        self.assertEqual(self.request("DELETE", "/api/ai")[0], 405)

    def test_refused_post_closes_so_its_body_is_never_a_request(self):
        import socket
        body = b'GET /ai HTTP/1.1\r\nHost: 127.0.0.1:%d\r\n\r\n' % self.port
        head = (f"POST /api/ai HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nOrigin: http://evil.example\r\n"
                f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode()
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(head + body)
            data = b""
            while chunk := sock.recv(65536):
                data += chunk
        self.assertEqual(data.count(b"HTTP/1.1 "), 1)
        self.assertTrue(data.startswith(b"HTTP/1.1 403 "))

    def test_repeated_security_headers_are_refused(self):
        token = self.token()
        for name, value in (("Host", f"127.0.0.1:{self.port}"), ("Origin", f"http://127.0.0.1:{self.port}"),
                            ("X-OPOS-Token", token)):
            with self.subTest(name=name):
                body = b'{"action":"reopen"}'
                head = (f"POST /api/ai HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n"
                        f"Origin: http://127.0.0.1:{self.port}\r\nX-OPOS-Token: {token}\r\n"
                        f"{name}: {value}\r\nContent-Type: application/json\r\n"
                        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n").encode()
                self.assertTrue(self.raw(head + body).startswith(b"HTTP/1.1 400 "))

    def test_get_with_a_body_and_odd_methods_close(self):
        reply = self.raw(f"GET /ai HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\nContent-Length: 4\r\n\r\n".encode()
                         + f"GET /ai HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
        self.assertEqual(reply.count(b"HTTP/1.1 "), 1)
        self.assertTrue(reply.startswith(b"HTTP/1.1 400 "))
        self.assertIn(b"Connection: close", reply)
        for method in ("HEAD", "OPTIONS", "BREW"):
            with self.subTest(method=method):
                reply = self.raw(f"{method} /api/ai HTTP/1.1\r\nHost: 127.0.0.1:{self.port}\r\n\r\n".encode())
                self.assertRegex(reply[:12], rb"HTTP/1.1 (405|501)")
                self.assertIn(b"X-Content-Type-Options: nosniff", reply)

    def test_http_1_0_post_is_answered_and_closed(self):
        token = self.token()
        body = b'{"action":"reopen"}'
        reply = self.raw((f"POST /api/ai HTTP/1.0\r\nHost: 127.0.0.1:{self.port}\r\nX-OPOS-Token: {token}\r\n"
                          f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n").encode() + body)
        self.assertTrue(reply.startswith(b"HTTP/1.0 200 ") or reply.startswith(b"HTTP/1.1 200 "), reply[:40])

    def raw(self, data):
        import socket
        with socket.create_connection(("127.0.0.1", self.port), timeout=5) as sock:
            sock.sendall(data)
            out = b""
            while chunk := sock.recv(65536):
                out += chunk
        return out

    def test_ask_and_refusal_over_http(self):
        self.enrolled()
        token = self.token()
        status, _, body = self.post({"action": "ask", "question": "Hello", "panes": ["phone", "gpu"]}, token)
        self.assertEqual(status, 200, body)
        self.assertEqual(json.loads(body)["gpu"]["answer"]["question"], "Hello")
        status, _, body = self.post({"action": "ask", "question": "Again", "panes": ["gpu"]}, token)
        self.assertEqual((status, json.loads(body)), (400, {"error": "Wait for this answer, or stop it."}))

    def test_binds_loopback_only(self):
        with self.assertRaises(ValueError):
            link_api.AppServer(self.api(), host="0.0.0.0", port=0)

    def test_stop_without_start_returns(self):
        server = link_api.AppServer(self.api(), port=0)
        done = threading.Event()
        threading.Thread(target=lambda: (server.stop(), done.set()), daemon=True).start()
        self.assertTrue(done.wait(3))


class RunnerTests(unittest.TestCase):
    def test_runner_serves_the_app_api(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(gpu_link_server.stop)
        self.addCleanup(ai_answers.reset)
        stop, apps, started, out = threading.Event(), [], threading.Event(), io.StringIO()

        def target():
            with contextlib.redirect_stdout(out):
                run_link.main(["--port", "0", "--app-port", "0", "--state-dir", temp.name],
                              stop=stop, ready=lambda port: started.set(), app_ready=apps.append)

        thread = threading.Thread(target=target)
        thread.start()
        self.addCleanup(thread.join, 10)
        self.addCleanup(stop.set)
        self.assertTrue(started.wait(10), out.getvalue())
        port = apps[0].port
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        connection.request("GET", "/ai")
        token = TOKEN_RE.search(connection.getresponse().read().decode()).group(1)
        connection.request("GET", "/api/ai", headers={"X-OPOS-Token": token})
        data = json.loads(connection.getresponse().read())
        connection.close()
        self.assertFalse(data["phone"]["ready"])
        self.assertEqual(data["gpu"]["link"]["enrol"], "open")
        self.assertIn(f"App API on http://127.0.0.1:{port}/api/ai (no phone lane).", out.getvalue())

    def test_phone_flags_go_together_and_stay_on_loopback(self):
        for argv in (["--phone-url", "http://127.0.0.1:8080/v1"], ["--phone-model", "m"],
                     ["--phone-url", "http://10.1.2.3:8080/v1", "--phone-model", "m"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                run_link.arguments(argv)
        args = run_link.arguments(["--phone-url", "http://127.0.0.1:8080/v1", "--phone-model", "m"])
        self.assertEqual(args.phone.model, "m")


if __name__ == "__main__":
    unittest.main()

"""Actual companion/backend compatibility through a socket-free HTTP adapter.

Set PHONE_TREE to the pristine deployed backend tree and PHONE_OVERLAY to the
new phone backend overlay. Each case copies only their Python source into a
temporary tree and runs in a fresh interpreter to isolate the two ``opos``
packages. No listener, model server, phone or optional package is used.
"""

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


CHILD = r'''
import contextlib
from email.message import Message
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from unittest.mock import patch

tree, companion, pair = map(Path, sys.argv[1:])
pair = str(pair)
sys.path.insert(0, str(tree / "src"))
from opos import ai_answers, ai_page, assist, muse, gpu_link_proto as phone_proto
from opos.ai_answers import AnswerStore
from opos.gpu_link import LinkService
from opos.store import Store

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    saved = list(sys.path)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = saved
    return module

old = pair == "old-new"
worker_root = companion.parent / "companion-r21-base" if old else companion
worker = load("compat_worker", worker_root / "gpu_link_worker.py")
worker.proto = load("compat_wire_proto", worker_root / "src/opos/gpu_link_proto.py")
assert worker.proto.PROTO == (1 if old else 2)
assert phone_proto.PROTO == (1 if pair == "new-old" else 2)
key = b"K" * 32  # Public deterministic fixture, never a real pairing key.
fallback = "Small (fallback for Original)"
now = [100.0]
clock = lambda: now[0]
counter = 0
def random_bytes(size):
    global counter
    counter += 1
    return counter.to_bytes(size, "big")

def forbidden(*args, **kwargs):
    raise AssertionError("compatibility tests must not use sockets or child programs")

os.environ.update(OPOS_STATE_DIR=str(tree / "state"), OPOS_APPS="ai",
                  OPOS_MODEL_POOL=str(tree / "missing-model-pool.json"))
with contextlib.ExitStack() as stack:
    for name in ("bind", "listen", "connect", "connect_ex"):
        stack.enter_context(patch.object(socket.socket, name, forbidden))
    stack.enter_context(patch.object(subprocess, "Popen", forbidden))
    store = Store(tree / "state")
    answers = AnswerStore(store)
    model = tree / "Original.gguf"
    model.write_bytes(b"fake model bytes")
    service = LinkService(answers, store, model, clock=clock, rand=random_bytes)
    stack.callback(service.close)
    if service._hasher is not None:
        service._hasher.join(2)
        assert not service._hasher.is_alive()

    def message(values):
        result = Message()
        for name, value in values.items():
            result[name] = value
        return result

    enrol_body = phone_proto.dumps({"pc_label": "Demo PC", "key": key.hex()})
    reply = service.handle("POST", "/v1/enrol", message({
        "Host": "localhost", "Content-Type": "application/json",
        "Content-Length": str(len(enrol_body))}), enrol_body)
    assert reply.status == 202
    assert service.allow(phone_proto.code("Demo PC", key))

    route = muse.Route("local", "Small local model", "on this phone",
                       "http://127.0.0.1:38641/v1", "fixture")
    stack.enter_context(patch.object(ai_answers, "shared", return_value=answers))
    stack.enter_context(patch.object(ai_page.gpu_link_server, "service", return_value=service))
    stack.enter_context(patch.object(assist, "local_route", return_value=route))
    stack.enter_context(patch.object(assist, "free_mb", return_value=2048))
    page = ai_page.PageState()
    stack.callback(page.close)
    requests = []
    replies = []

    class Response:
        def __init__(self, reply):
            self.status, self.body, self.fields = reply.status, reply.body, reply.headers
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
        def __init__(self, *_args, **_kwargs):
            pass
        def request(self, method, target, body=b"", headers=None):
            fields = dict(headers or {})
            if method == "POST":
                # HTTPConnection normally supplies framing before transmission.
                fields.setdefault("Content-Length", str(len(body)))
            requests.append((method, target, body, fields))
            now[0] += 0.5
            reply = service.handle(method, target, message(fields), body)
            if reply.sent is not None:
                reply.sent()
            replies.append((target, reply.status, reply.body))
            self.response = Response(reply)
        def getresponse(self):
            return self.response
        def close(self):
            pass

    stack.enter_context(patch.object(worker.http.client, "HTTPConnection", Connection))
    pc = worker.PC("127.0.0.1:38641", key, label="Demo PC")
    pc.lead_label = fallback
    pc.hello()  # Actual hello validation, including the old client's strict proto.
    for _ in range(3):
        status, value = pc.status()
        assert status == 200
        assert value == ({"cancel": None, "proto": 2} if pair == "new-new" else {"cancel": None})

    sent = [json.loads(body) for method, target, body, _ in requests
            if method == "POST" and target == "/v1/status"]
    assert len(sent) == 3
    if pair != "new-new":
        assert all("lead_label" not in item for item in sent)
        assert service.snapshot()["pc"].get("lead_label") is None
        assert "lead_label" not in page.snapshot()["gpu"]
        assert page.snapshot()["gpu"]["model"] == "Original"
        if old:
            assert all("X-Link-Proto" not in fields for _, _, _, fields in requests)
            assert json.loads(replies[0][2])["proto"] == 1
            assert all(set(json.loads(body)) == {"cancel"}
                       for target, status, body in replies if target == "/v1/status")
    else:
        assert "lead_label" not in sent[0]  # The first status negotiates support.
        assert sent[1]["lead_label"] == fallback
        assert service.snapshot()["pc"]["lead_label"] == fallback
        snapshot = page.snapshot()
        assert snapshot["gpu"]["lead_label"] == fallback
        assert snapshot["gpu"]["model"] == fallback
        assert snapshot["gpu"]["link"]["model"]["name"] == "Original"

        # A finished failure is the event that causes runtime fallback. Show
        # the current fallback byline without rewriting the stored old answer.
        answer = answers.ask("gpu", "question that failed")
        answers.note(answer["id"], model="Original", where="Demo PC")
        answers.fail(answer["id"], "stream_error")
        pc.status()
        snapshot = page.snapshot()
        assert snapshot["gpu"]["lead_label"] == fallback
        assert snapshot["gpu"]["answer"]["model"] == "Original"
        assert snapshot["gpu"]["answer"]["state"] == "failed"

        pc.lead_label = None
        assert pc.status()[0] == 200
        assert json.loads(requests[-1][2])["lead_label"] is None
        assert service.snapshot()["pc"].get("lead_label") is None
        assert "lead_label" not in page.snapshot()["gpu"]
        assert page.snapshot()["gpu"]["answer"]["model"] == "Original"
print("COMPAT_PAIR=" + pair + " PASSED (actual PC, LinkService, PageState; fake HTTP)")
'''


class BackendCompatibility(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree, overlay = os.environ.get("PHONE_TREE"), os.environ.get("PHONE_OVERLAY")
        if not tree or not overlay:
            raise unittest.SkipTest("set PHONE_TREE and PHONE_OVERLAY for actual backend compatibility fixtures")
        cls.phone_tree, cls.phone_overlay = Path(tree), Path(overlay)
        for root in (cls.phone_tree, cls.phone_overlay):
            if not (root / "src/opos/gpu_link.py").is_file():
                raise AssertionError("PHONE_TREE/PHONE_OVERLAY must contain src/opos/gpu_link.py")
        cls.companion = Path(__file__).resolve().parent

    def check_pair(self, pair):
        with tempfile.TemporaryDirectory(prefix="gpu-link-peer-compat-") as directory:
            tree = Path(directory)
            shutil.copytree(self.phone_tree / "src", tree / "src")
            if pair != "new-old":
                shutil.copytree(self.phone_overlay / "src", tree / "src", dirs_exist_ok=True)
            result = subprocess.run(
                [sys.executable, "-B", "-c", CHILD, str(tree), str(self.companion),
                 pair], cwd=tree, capture_output=True, text=True,
                timeout=20, check=False)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("COMPAT_PAIR=" + pair + " PASSED", result.stdout)

    def test_new_companion_old_backend_keeps_legacy_status(self):
        self.check_pair("new-old")

    def test_old_companion_new_backend_keeps_strict_reply_shapes(self):
        self.check_pair("old-new")

    def test_new_peers_store_show_and_clear_label_with_finished_history(self):
        self.check_pair("new-new")


if __name__ == "__main__":
    unittest.main()

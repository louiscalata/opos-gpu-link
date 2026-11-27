# SPDX-License-Identifier: Apache-2.0
"""A model server that goes quiet after its first event is a stall after STALL_SECONDS, not 30 s."""
from __future__ import annotations

import http.server
import os
import threading
import time
import unittest
from unittest.mock import patch

import gpu_link_worker as worker

EVENT = b'data: {"choices":[{"delta":{"content":"Step one. "}}]}\n\n'
END = b'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'


class Handler(http.server.BaseHTTPRequestHandler):
    """Script: optional delay before the first byte, an optional comment, one event, then quiet or end."""

    script = {"before": 0.0, "comment": False, "end": False}
    release = threading.Event()

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if self.script["comment"]:
            self.wfile.write(b": warming up\n\n")
            self.wfile.flush()
        self.release.wait(self.script["before"])
        self.wfile.write(EVENT)
        if self.script["end"]:
            self.wfile.write(END)
            self.wfile.flush()
            return
        self.wfile.flush()
        self.release.wait(10)  # quiet; released at cleanup

    def log_message(self, *args):
        pass


class StallTimeout(unittest.TestCase):
    def serve(self, **script):
        Handler.script = {"before": 0.0, "comment": False, "end": False, **script}
        Handler.release = threading.Event()
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(Handler.release.set)
        return f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"

    def run_source(self, url, guard="0"):
        with patch.dict(os.environ, {"OPOS_GPU_LINK_STALL_SECONDS": "1", "OPOS_GPU_LINK_GUARD": guard}):
            started = time.monotonic()
            source = worker.ServerSource({"question": "Q", "partial": ""}, url, "m")
            self.addCleanup(source.close)
            source.worker.join(8)
            self.assertFalse(source.worker.is_alive(), "reader did not finish")
            return source, time.monotonic() - started

    def test_quiet_stream_after_first_event_is_a_server_stall(self):
        source, elapsed = self.run_source(self.serve())
        self.assertLess(elapsed, 8)  # well under the 30 s read timeout
        data, done, _finish, _tokens, error = source.snapshot()
        self.assertTrue(done)
        self.assertTrue(error)
        self.assertEqual(source.error_code, "server")  # recoverable: pause and resume
        self.assertEqual(data, b"Step one. ")  # the text so far is kept

    @unittest.skipIf(worker.GuardState is None, "guard module not available")
    def test_stall_with_the_guard_on_is_still_a_server_stall(self):
        source, _elapsed = self.run_source(self.serve(), guard="1")
        data, done, _finish, _tokens, error = source.snapshot()
        self.assertTrue(done and error)
        self.assertEqual(source.error_code, "server")
        # The guard holds back an unchecked tail, as for a crash; resume regenerates it.
        self.assertTrue(b"Step one. ".startswith(data))

    def test_slow_first_event_keeps_the_long_wait(self):
        # 2 s to the first event is longer than STALL_SECONDS (1 s) but under the 30 s first-byte wait.
        source, _elapsed = self.run_source(self.serve(before=2.0, comment=True, end=True))
        data, done, finish, _tokens, error = source.snapshot()
        self.assertTrue(done)
        self.assertFalse(error)
        self.assertEqual(finish, "stop")
        self.assertEqual(data, b"Step one. ")

    def test_stall_seconds_is_clamped(self):
        for raw, expected in (("12", 12.0), ("5", 5.0), ("0", 1.0), ("45", 30.0), ("x", 12.0), ("nan", 12.0)):
            with patch.dict(os.environ, {"OPOS_GPU_LINK_STALL_SECONDS": raw}):
                self.assertEqual(worker._stall_seconds(), expected)
        with patch.dict(os.environ, {}):
            os.environ.pop("OPOS_GPU_LINK_STALL_SECONDS", None)
            self.assertEqual(worker._stall_seconds(), 12.0)
        self.assertEqual(worker.ServerSource.FIRST_BYTE_SECONDS, 30)


if __name__ == "__main__":
    unittest.main()

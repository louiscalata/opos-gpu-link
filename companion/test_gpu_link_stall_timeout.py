# SPDX-License-Identifier: Apache-2.0
"""A model server that goes quiet after its first bytes is a stall after STALL_SECONDS, not 30 s."""
from __future__ import annotations

import http.server
import os
import threading
import time
import unittest
from unittest.mock import patch

import gpu_link_worker as worker

EVENT = b'data: {"choices":[{"delta":{"content":"Step one. "}}]}\n\n'


class Quiet(http.server.BaseHTTPRequestHandler):
    hold = 3.0

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        self.wfile.write(EVENT)
        self.wfile.flush()
        time.sleep(self.hold)  # quiet, never closes in time

    def log_message(self, *args):
        pass


class StallTimeout(unittest.TestCase):
    def serve(self):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Quiet)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}/v1/chat/completions"

    def test_quiet_stream_after_first_bytes_is_a_server_stall(self):
        url = self.serve()
        with patch.dict(os.environ, {"OPOS_GPU_LINK_STALL_SECONDS": "1", "OPOS_GPU_LINK_GUARD": "0"}):
            started = time.monotonic()
            source = worker.ServerSource({"question": "Q", "partial": ""}, url, "m")
            try:
                source.worker.join(2.5)
                self.assertFalse(source.worker.is_alive(), "stall not noticed within 2.5 s")
                self.assertLess(time.monotonic() - started, 2.5)
                data, done, _finish, _tokens, error = source.snapshot()
                self.assertTrue(done)
                self.assertTrue(error)
                self.assertEqual(source.error_code, "server")  # recoverable: pause and resume
                self.assertEqual(data, b"Step one. ")  # the text so far is kept
            finally:
                source.close()

    def test_stall_seconds_is_bounded(self):
        for raw, expected in (("12", 12.0), ("0", 12.0), ("31", 12.0), ("x", 12.0), ("5", 5.0)):
            with patch.dict(os.environ, {"OPOS_GPU_LINK_STALL_SECONDS": raw}):
                self.assertEqual(worker._stall_seconds(), expected)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPOS_GPU_LINK_STALL_SECONDS", None)
            self.assertEqual(worker._stall_seconds(), 12.0)

    def test_first_byte_keeps_the_long_wait(self):
        self.assertEqual(worker.ServerSource.FIRST_BYTE_SECONDS, 30)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""The standalone runner starts the loopback listener, reports its port and stops cleanly."""

from __future__ import annotations

import contextlib
import io
import socket
import sys
import tempfile
import threading
import os
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_link  # noqa: E402
from opos import ai_answers, gpu_link_server  # noqa: E402


class RunLinkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        self.addCleanup(gpu_link_server.stop)
        self.addCleanup(ai_answers.reset)

    def run_runner(self, *extra):
        stop, ports = threading.Event(), []
        started = threading.Event()

        def ready(port):
            ports.append(port)
            started.set()

        out = io.StringIO()
        result = []

        def target():
            with contextlib.redirect_stdout(out):
                result.append(run_link.main(["--port", "0", "--no-app-api", "--state-dir", self.temp.name, *extra],
                                            stop=stop, ready=ready))

        thread = threading.Thread(target=target)
        thread.start()
        self.assertTrue(started.wait(10), out.getvalue())
        return stop, thread, ports[0], out, result

    def test_listens_on_loopback_and_stops(self):
        stop, thread, port, out, result = self.run_runner("--label", "Test phone")
        self.assertGreater(port, 0)
        self.assertIsNotNone(gpu_link_server.service())
        with socket.create_connection(("127.0.0.1", port), timeout=5):
            pass
        stop.set()
        thread.join(10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [0])
        self.assertIsNone(gpu_link_server.service())
        self.assertIsNone(gpu_link_server.listening_port())
        with self.assertRaises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
        self.assertIn("Test phone", out.getvalue())

    def test_environment_turns_the_link_on(self):
        args = run_link.arguments(["--port", "9999", "--label", "Phone", "--state-dir", self.temp.name])
        env = run_link.environment(args)
        self.assertEqual(env["OPOS_GPU_LINK"], "1")
        self.assertEqual(env["OPOS_GPU_LINK_PORT"], "9999")
        self.assertEqual(env["XDG_STATE_HOME"], self.temp.name)
        self.assertNotIn("OPOS_GPU_LINK_MODEL", env)

    def test_rejects_bad_arguments(self):
        for argv in (["--port", "70000"], ["--port", "-1"], ["--model", str(Path(self.temp.name) / "missing.gguf")]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    run_link.arguments(argv)
                self.assertEqual(caught.exception.code, 2)


if __name__ == "__main__":
    unittest.main()

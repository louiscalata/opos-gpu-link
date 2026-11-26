# SPDX-License-Identifier: Apache-2.0
"""Isolated discovery and launcher checks. No native adb or model backend is used."""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import gpu_link_discover as discovery
import opos_gpu_link as link


class RecordingSocket:
    def __init__(self, response, requests):
        self.response = response
        self.requests = requests

    def sendall(self, data):
        self.requests.append(data)

    def makefile(self, *_args):
        return io.BytesIO(self.response)

    def shutdown(self, *_args):
        pass

    def close(self):
        pass


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.connections = []
        payload = b'{"data":[{"id":"local-model","owned_by":"vllm"}]}'
        self.response = (b"HTTP/1.1 200 OK\r\nContent-Length: "
                         + str(len(payload)).encode() + b"\r\n\r\n" + payload)

    def connect(self, address, timeout, *_args):
        self.connections.append((address, timeout))
        return RecordingSocket(self.response, self.requests)

    def test_default_never_connects_to_protected_ports(self):
        ports = (1234, 1236, 8080, 8081, 8765, 8767, 11434, 11435, 4173)
        urls = [f"http://127.0.0.1:{port}/v1" for port in ports]
        with patch.object(socket, "create_connection", side_effect=self.connect):
            for url in urls:
                with self.subTest(url=url), patch.dict(os.environ, OPENAI_BASE_URL=url):
                    self.connections.clear()
                    discovery.discover()
                    self.assertEqual(self.connections, [(("127.0.0.1", 1235), 2),
                                                        (("127.0.0.1", 8000), 2)])
            self.connections.clear()
            discovery.discover(urls)
            self.assertEqual([address[1] for address, _ in self.connections], [1235, 8000])

    def test_protected_opt_in_needs_explicit_url_and_flag(self):
        with patch.object(socket, "create_connection", side_effect=self.connect), \
                patch.dict(os.environ, OPENAI_BASE_URL="http://127.0.0.1:8081/v1"):
            discovery.discover(["http://localhost:8080/v1"], allow_protected=True)
        self.assertEqual([address[1] for address, _ in self.connections], [8080, 1235, 8000])

    def test_loopback_only_deduplicated_and_read_only(self):
        with patch.object(socket, "create_connection", side_effect=self.connect), \
                patch.dict(os.environ, OPENAI_BASE_URL="http://localhost:18191/v1"), \
                patch.object(discovery, "DEFAULT_URLS", ()):
            backends = discovery.discover(["http://127.0.0.1:18191",
                                           "http://192.0.2.1:18191",
                                           "http://example.invalid",
                                           "http://user@localhost:18191",
                                           "http://localhost:18191/v1?token=ignored"])
        self.assertEqual(self.connections, [(("127.0.0.1", 18191), 2)])
        self.assertEqual(backends, [{"url": "http://127.0.0.1:18191",
                                     "kind": "vLLM", "models": ["local-model"]}])
        self.assertEqual(len(self.requests), 1)
        self.assertTrue(self.requests[0].startswith(b"GET /v1/models HTTP/1.1\r\n"))
        self.assertNotIn(b"Authorization:", self.requests[0])

    def test_backend_kind_uses_server_header_and_has_generic_fallback(self):
        payload = b'{"object":"list","data":[{"id":"example"}]}'
        with patch.object(socket, "create_connection", side_effect=self.connect), \
                patch.dict(os.environ, OPENAI_BASE_URL=""), \
                patch.object(discovery, "DEFAULT_URLS", ()):
            for header, kind in ((b"LM Studio", "LM Studio"), (b"llama.cpp", "llama.cpp"),
                                 (b"Ollama", "Ollama"), (b"uvicorn", "OpenAI-compatible")):
                with self.subTest(header=header):
                    self.response = (b"HTTP/1.1 200 OK\r\nServer: " + header
                                     + b"\r\nContent-Length: " + str(len(payload)).encode()
                                     + b"\r\n\r\n" + payload)
                    self.assertEqual(discovery.discover(["http://127.0.0.1:18191"]), [
                        {"url": "http://127.0.0.1:18191", "kind": kind, "models": ["example"]},
                    ])

    def test_redirect_is_never_followed(self):
        self.response = (b"HTTP/1.1 302 Found\r\nLocation: http://127.0.0.1:8080/v1/models\r\n"
                         b"Content-Length: 0\r\n\r\n")
        with patch.object(socket, "create_connection", side_effect=self.connect), \
                patch.dict(os.environ, OPENAI_BASE_URL=""), \
                patch.object(discovery, "DEFAULT_URLS", ()):
            self.assertEqual(discovery.discover(["http://127.0.0.1:18191"]), [])
        self.assertEqual(len(self.connections), 1)

    def test_json_discovery_skips_phone_and_pairing(self):
        output = io.StringIO()
        with patch.object(socket, "create_connection", side_effect=self.connect), \
                patch.dict(os.environ, OPENAI_BASE_URL=""), \
                patch.object(link, "select_serial", side_effect=AssertionError("adb called")), \
                patch.object(link, "InstanceGuard", side_effect=AssertionError("pairing accessed")), \
                patch.object(discovery.shutil, "which", side_effect=lambda name: "/tools/lms" if
                             name == "lms" else None), contextlib.redirect_stdout(output):
            self.assertEqual(link.main(["--discover", "--json", "--reset-pairing"]), 0)
        report = json.loads(output.getvalue())
        self.assertEqual(report["backends"][0]["models"], ["local-model"])
        self.assertEqual(report["tools"]["lms"], {"present": True, "path": "/tools/lms"})
        self.assertEqual(report["tools"]["llama-server"], {"present": False, "path": None})

    def test_normal_start_selects_only_a_single_unprotected_backend(self):
        for ports, selected in [([18191], 18191), ([8080], 1235), ([], 1235), ([18191, 8000], 1235)]:
            with self.subTest(ports=ports):
                backends = [{"url": f"http://127.0.0.1:{port}"} for port in ports]
                output = io.StringIO()
                with patch.object(discovery, "discover", return_value=backends), \
                        patch.object(link, "resolve_launch_adb", side_effect=lambda adb, runner=None: adb), \
                        patch.object(link, "InstanceGuard"), patch.object(link, "Companion") as app, \
                        contextlib.redirect_stdout(output):
                    app.return_value.cleanup_ok = True
                    self.assertEqual(link.main(["--headless", "--serial", "PHONE", "--model", "local"]), 0)
                self.assertEqual(app.call_args.args[0].server,
                                 f"http://127.0.0.1:{selected}/v1/chat/completions")
                if selected != 1235:
                    self.assertIn(f"Using discovered backend http://127.0.0.1:{selected}", output.getvalue())

    def test_explicit_backend_requires_exact_opt_in_for_protected_ports(self):
        url = "http://127.0.0.1:8080/v1"
        with contextlib.redirect_stderr(io.StringIO()):
            for opt_in in ([], ["--allow-protected-port"], ["--probe-url", url],
                           ["--allow-protected-port", "--probe-url", "http://localhost:8080/v1"]):
                with self.subTest(opt_in=opt_in), self.assertRaises(SystemExit):
                    link.arguments(["--model", "local", "--lm-url", url, *opt_in])
            with self.assertRaises(SystemExit):
                link.arguments(["--model", "local", "--server", url + "/chat/completions"])
        args = link.arguments(["--model", "local", "--lm-url", url,
                               "--allow-protected-port", "--probe-url", url])
        self.assertFalse(args.auto_discover)
        self.assertEqual(args.server, url + "/chat/completions")

    def test_two_http_backends_use_their_own_responses(self):
        requests, connections = [], []
        backends = {38121: ("LM Studio", "model-one"), 38122: ("llama.cpp", "model-two")}

        def connect(address, timeout, *_args):
            self.assertEqual(address[0], "127.0.0.1")
            self.assertEqual(timeout, discovery.TIMEOUT)
            connections.append(address)
            kind, model = backends[address[1]]
            payload = json.dumps({"data": [{"id": model}]}).encode()
            response = (b"HTTP/1.1 200 OK\r\nServer: " + kind.encode()
                        + b"\r\nContent-Length: " + str(len(payload)).encode()
                        + b"\r\n\r\n" + payload)
            return RecordingSocket(response, requests)

        urls = [f"http://127.0.0.1:{port}" for port in backends]
        with patch.object(socket, "create_connection", side_effect=connect), \
                patch.dict(os.environ, OPENAI_BASE_URL=urls[1] + "/v1"), \
                patch.object(discovery, "DEFAULT_URLS", ()):
            self.assertEqual(discovery.discover([urls[0]]), [
                {"url": urls[0], "kind": "LM Studio", "models": ["model-one"]},
                {"url": urls[1], "kind": "llama.cpp", "models": ["model-two"]},
            ])
        self.assertEqual(connections, [("127.0.0.1", port) for port in backends])
        self.assertEqual(len(requests), 2)
        self.assertTrue(all(request.startswith(b"GET /v1/models HTTP/1.1\r\n") for request in requests))


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux launcher")
class LinuxLauncherTests(unittest.TestCase):
    launcher = Path(__file__).with_name("run-linux.sh").resolve()

    def test_bash_syntax_and_help(self):
        subprocess.run(["bash", "-n", self.launcher], check=True)
        result = subprocess.run([self.launcher, "--help"], check=True, capture_output=True, text=True)
        for option in ("--discover", "--adb", "--key-dir", "--serial", "--always-allow"):
            self.assertIn(option, result.stdout)

    @unittest.skipUnless(shutil.which("shellcheck"), "shellcheck unavailable")
    def test_shellcheck(self):
        subprocess.run(["shellcheck", self.launcher], check=True)

    def test_sdk_adb_discovery_and_flag_passthrough(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            tools_dir = root / "tools"
            tools_dir.mkdir()
            (tools_dir / "bash").symlink_to(shutil.which("bash"))
            (tools_dir / "dirname").symlink_to(shutil.which("dirname"))
            sdk_adb = root / "Android/Sdk/platform-tools/adb"
            sdk_adb.parent.mkdir(parents=True)
            sdk_adb.touch(mode=0o700)
            fake_python = root / "python"
            fake_python.write_text("#!/bin/sh\nprintf '%s\\n' \"$@\"\n")
            fake_python.chmod(0o700)
            env = dict(os.environ, HOME=str(root), PATH=str(tools_dir),
                       OPOS_GPU_LINK_PYTHON=str(fake_python))
            options = ["--key-dir", str(root / "pairing dir"), "--serial", "PHONE", "--adb", "override"]
            result = subprocess.run([self.launcher, *options], env=env, check=True,
                                    capture_output=True, text=True)
            self.assertEqual(result.stdout.splitlines(), [
                "-B", "opos_gpu_link.py", "--headless", "--always-allow", "--adb", str(sdk_adb), *options,
            ])

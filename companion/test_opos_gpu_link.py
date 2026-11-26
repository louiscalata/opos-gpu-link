# SPDX-License-Identifier: Apache-2.0
"""Isolated companion checks. The fake runner never invokes real adb."""

import contextlib
import hashlib
import io
import json
import os
import queue
import signal
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import ANY, patch

import opos_gpu_link as link
from gpu_link_worker import ServerSource, StopRequested, ToolError, checked_reply, proto


class FakeAdb:
    def __init__(self):
        self.state = "unauthorized"
        self.assigned = [1235, 18767, 18768]
        self.forwards = {}
        self.calls = []
        self.phone_allowed = False
        self.enrol_sent = False
        self.fail_list_once = False

    def __call__(self, command, **kwargs):
        args = command[1:]
        self.calls.append((args, kwargs.get("input")))
        out = b""
        if args == ["devices"]:
            out = f"List of devices attached\nPHONE\t{self.state}\n".encode()
        elif args == ["devices", "-l"]:
            out = f"List of devices attached\nPHONE\t{self.state} usb:1-1\n".encode()
        elif args == ["forward", "--list"]:
            if self.fail_list_once:
                self.fail_list_once = False
                return SimpleNamespace(returncode=1, stdout=b"", stderr=b"temporary failure")
            out = b"".join(f"PHONE tcp:{port} tcp:8767\n".encode()
                           for port in self.forwards)
        elif args == ["-s", "PHONE", "forward", "tcp:0", "tcp:8767"]:
            port = self.assigned.pop(0)
            self.forwards[port] = True
            out = str(port).encode() + b"\n"
        elif len(args) == 5 and args[:4] == ["-s", "PHONE", "forward", "--remove"]:
            self.forwards.pop(int(args[4][4:]), None)
        elif args == ["-s", "PHONE", "shell", "am", "start", "-n",
                      "os.opos.launcher/.MainActivity"]:
            out = b"Starting: Intent\n"
        elif args == ["-s", "PHONE", "shell", "-T", "nc", "127.0.0.1", "8767"]:
            self.enrol_sent = True
            body = b'{"state":"pending"}'
            out = (b"HTTP/1.1 202 Accepted\r\nContent-Length: 19\r\n"
                   b"Connection: close\r\n\r\n" + body)
        else:
            raise AssertionError(f"unexpected fake adb call: {args}")
        return SimpleNamespace(returncode=0, stdout=out, stderr=b"")


class FakePC:
    def __init__(self, phone, key, label):
        self.phone, self.key, self.label = phone, key, label

    def hello(self):
        return None

    def enrol_request(self):
        return b"fake enrolment request"


def app_fixture(directory, fake, now):
    args = SimpleNamespace(serial="PHONE", adb="fake-adb", label="OPOS GPU PC",
                           no_launch=True, key_dir=Path(directory),
                           server=link.DEFAULT_SERVER, model="local",
                           always_allow=True)
    app = link.Companion.__new__(link.Companion)
    app.args = args
    app.bridge = link.AdbBridge("fake-adb", "PHONE", runner=fake,
                                owner_checker=lambda port, adb: True)
    app.keys = link.KeyStore(args.key_dir, args.serial)
    app.clock = lambda: now[0]
    app.running = True
    app.headless = True
    app.wake = threading.Event()
    app.events = queue.SimpleQueue()
    app.lines = []
    app.status = SimpleNamespace(set=app.lines.append)
    app.online = False
    app.granted = True
    app.detached_at = None
    app.blocked_until_detach = False
    app.worker = None
    app.worker_stop = None
    app.next_try = 0
    app.pending_key = None
    app.session_pc = None
    app.session_launch_failed = False
    app.preflight_thread = None
    app.preflight_done = None
    app.preflight_cancel = None
    app.preflight_result = False
    app.retry_delay = 3
    app.starts = 0

    def start_worker(pc):
        app.starts += 1
        app.worker_stop = threading.Event()
        app.worker = SimpleNamespace(is_alive=lambda: not app.worker_stop.is_set(),
                                     join=lambda timeout: None)

    app._start_worker = start_worker
    return app


def finish_preflight(app):
    assert app.preflight_done is not None
    assert app.preflight_done.wait(2), "host preflight did not finish"
    app.tick()


class CompanionTests(unittest.TestCase):
    def test_pc_fingerprint_is_stable_nonsecret_header_id(self):
        key = bytes(range(32))
        fingerprint = link.proto.pc_id(key)
        self.assertEqual(fingerprint, hashlib.sha256(key).hexdigest()[:16])
        self.assertNotEqual(fingerprint, key.hex())

    def test_unauthorized_device_never_gets_a_forward(self):
        fake = FakeAdb()
        bridge = link.AdbBridge("fake-adb", "PHONE", runner=fake,
                                owner_checker=lambda port, adb: True)
        self.assertFalse(bridge.authorized())
        self.assertEqual([args for args, _ in fake.calls], [["devices", "-l"]])

    def test_forward_rejects_reserved_port_and_recreates_on_replug(self):
        fake = FakeAdb()
        fake.state = "device"
        bridge = link.AdbBridge("fake-adb", "PHONE", runner=fake,
                                owner_checker=lambda port, adb: True)
        self.assertTrue(bridge.authorized())
        self.assertEqual(bridge.create_forward(), 18767)
        self.assertNotIn(1235, fake.forwards)
        self.assertTrue(bridge.forward_present())
        bridge.launch_models()
        bridge.remove_own_forward()
        self.assertEqual(bridge.create_forward(), 18768)
        self.assertFalse(any("--remove-all" in args for args, _ in fake.calls))

    def test_forward_refuses_unverified_listener(self):
        fake = FakeAdb()
        fake.state = "device"
        fake.assigned = [18767]
        bridge = link.AdbBridge("fake-adb", "PHONE", runner=fake,
                                owner_checker=lambda port, adb: False)
        with self.assertRaisesRegex(link.CompanionError, "Could not verify.*not a queued computer answer"):
            bridge.create_forward()
        self.assertEqual(fake.forwards, {})

    def test_resolve_launch_adb_uses_the_running_server(self):
        from test_gpu_link_autosetup import _adb_lsof_runner
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            path_adb = root / "path" / "adb"
            server_adb = root / "server" / "adb"
            path_adb.parent.mkdir()
            server_adb.parent.mkdir()
            path_adb.write_text("")
            server_adb.write_text("")
            path_adb.chmod(0o755)
            server_adb.chmod(0o755)
            runner = _adb_lsof_runner(
                listen="p4242\nn127.0.0.1:5037\n",
                txt="n%s\n" % server_adb,
            )
            got = link.resolve_launch_adb(str(path_adb), runner=runner, system="linux")
            self.assertEqual(Path(got).resolve(), server_adb.resolve())

    def _force_autosetup_import_error(self):
        import builtins
        real_import = builtins.__import__
        def fake_import(name, *args, **kwargs):
            if name == "gpu_link_autosetup":
                raise ImportError("forced")
            return real_import(name, *args, **kwargs)
        return patch("builtins.__import__", fake_import)

    def test_resolve_launch_adb_import_error_keeps_an_explicit_path(self):
        with tempfile.TemporaryDirectory() as d:
            adb = Path(d) / "sdk" / "adb"
            adb.parent.mkdir()
            adb.write_text("")
            adb.chmod(0o755)
            with self._force_autosetup_import_error(), \
                    patch.object(link.shutil, "which", return_value=None):
                got = link.resolve_launch_adb(str(adb))
            self.assertEqual(Path(got).resolve(), adb.resolve())

    def test_resolve_launch_adb_import_error_rejects_cwd_file_for_bare_adb(self):
        with tempfile.TemporaryDirectory() as d:
            cwd_adb = Path(d) / "adb"
            cwd_adb.write_text("")
            cwd_adb.chmod(0o755)
            import os
            old = os.getcwd()
            try:
                os.chdir(d)
                with self._force_autosetup_import_error(), \
                        patch.object(link.shutil, "which", return_value=None), \
                        self.assertRaises(link.CompanionError):
                    link.resolve_launch_adb("adb")
            finally:
                os.chdir(old)

    def test_resolve_launch_adb_import_error_keeps_relative_explicit_path(self):
        with tempfile.TemporaryDirectory() as d:
            local = Path(d) / "adb"
            local.write_text("")
            local.chmod(0o755)
            import os
            old = os.getcwd()
            try:
                os.chdir(d)
                with self._force_autosetup_import_error(), \
                        patch.object(link.shutil, "which", return_value=None):
                    got = link.resolve_launch_adb("./adb")
                self.assertEqual(Path(got).resolve(), local.resolve())
                self.assertTrue(Path(got).is_absolute())
            finally:
                os.chdir(old)

    def test_pairing_key_saves_only_when_called_and_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            store = link.KeyStore(Path(directory), "PHONE")
            key = bytes(range(32))
            self.assertIsNone(store.load())
            store.save_first_allow(key)
            self.assertEqual(store.load(), key)
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(store.path.stat().st_mode), 0o600)
            with self.assertRaises(link.CompanionError):
                store.save_first_allow(bytes(reversed(key)))

    def test_existing_key_connects_without_enrolment(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            app = app_fixture(directory, fake, [100.0])
            app.keys.save_first_allow(bytes(range(32)))
            app.detached_at = 42
            app.permission = lambda: self.fail("saved trust must not prompt")
            with patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", return_value=True):
                app._connect()
                finish_preflight(app)
            self.assertTrue(app.online)
            self.assertIsNone(app.detached_at)
            self.assertEqual(app.starts, 1)
            self.assertFalse(any("nc" in args for args, _ in fake.calls))

    def test_headless_first_pair_prints_code_and_saves_only_after_phone_allow(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767]
            app = app_fixture(directory, fake, [100.0])
            app.status = link.ConsoleStatus()
            app.permission = lambda: self.fail("headless pairing must not create Tk permission")
            output = io.StringIO()

            def signed_idle(pc):
                self.assertIsNone(app.keys.load())
                if fake.enrol_sent:
                    fake.phone_allowed = True  # Owner taps Allow after seeing the code.
                return fake.phone_allowed

            with contextlib.redirect_stdout(output), patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", side_effect=signed_idle), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", return_value=True):
                app._connect()
                finish_preflight(app)
            self.assertTrue(app.online)
            self.assertEqual(app.starts, 1)
            self.assertEqual(len(app.keys.load()), link.proto.KEY_BYTES)
            self.assertIsNone(app.pending_key)
            self.assertIn("Compare code ", output.getvalue())
            self.assertIn("Allow this PC", output.getvalue())
            self.assertNotIn("fake enrolment request", output.getvalue())
            self.assertEqual(sum("nc" in args for args, _ in fake.calls), 1)

    def test_headless_phone_allow_after_deadline_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.link_present = lambda: True
            pc = FakePC("127.0.0.1:18767", bytes(range(32)), "OPOS GPU PC")

            def slow_signed_status(pc):
                now[0] = 161.0
                return True

            with patch.object(link, "authenticated_idle", side_effect=slow_signed_status):
                self.assertFalse(app.wait_for_phone_allow(pc))

    def test_stop_during_first_pair_does_not_start_worker_or_save_key(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767]
            app = app_fixture(directory, fake, [100.0])
            app.wait_for_phone_allow = lambda pc: (app.stop() or True)
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=False):
                app._connect()
            self.assertEqual(app.starts, 0)
            self.assertIsNone(app.keys.load())
            self.assertEqual(fake.forwards, {})

    def test_stop_between_worker_assignment_and_start_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            app = app_fixture(directory, FakeAdb(), [100.0])
            del app._start_worker  # Exercise the real method instead of the fixture stub.

            class InterruptingThread:
                def __init__(self, **kwargs):
                    self.alive = False

                def is_alive(self):
                    return self.alive

                def start(self):
                    app.stop()  # Signal arrives after worker assignment.
                    self.alive = True

                def join(self, timeout):
                    self.alive = False

            with patch.object(link.threading, "Thread", InterruptingThread):
                app._start_worker(FakePC("127.0.0.1:18767", bytes(range(32)), "OPOS GPU PC"))
            self.assertFalse(app.running)
            self.assertIsNone(app.worker)

    def test_saved_key_unplug_replug_restarts_worker_without_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767, 18768]
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.keys.save_first_allow(bytes(range(32)))
            app.permission = lambda: self.fail("replug must not prompt")
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", return_value=True):
                app.tick()
                finish_preflight(app)
                self.assertEqual(app.starts, 1)
                fake.state = "unauthorized"
                now[0] = 101.0
                app.tick()
                self.assertFalse(app.online)
                self.assertEqual(fake.forwards, {})
                fake.state = "device"
                now[0] = 104.0
                app.tick()
                finish_preflight(app)
            self.assertTrue(app.online)
            self.assertEqual(app.starts, 2)
            self.assertEqual(list(fake.forwards), [18768])
            self.assertFalse(any("nc" in args for args, _ in fake.calls))

    def test_replug_after_adbd_restart_resumes_by_itself_and_never_opens_app_while_backend_down(self):
        """Physical cable pull: adb forgets every forward, adbd restarts and the phone
        service is briefly gone. Nothing may need a tap: forwards are rebuilt, the app is
        not pulled to the front until the phone service answers, and workers restart."""
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = list(range(18767, 18800))
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.args.no_launch = False
            app.keys.save_first_allow(bytes(range(32)))
            backend = [True]

            def idle(pc):
                if not backend[0]:
                    raise OSError("connection refused")
                return True

            launches = lambda: sum(a[2:5] == ["shell", "am", "start"] for a, _ in fake.calls)
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", side_effect=idle), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", return_value=True):
                app.tick()
                finish_preflight(app)
                self.assertTrue(app.online)
                self.assertEqual((app.starts, launches()), (1, 1))
                # Cable pulled: the device vanishes, the forwards are gone and the phone
                # backend is dead when the cable returns.
                fake.state = "offline"
                fake.forwards.clear()
                backend[0] = False
                now[0] = 101.0
                app.tick()
                self.assertFalse(app.online)
                fake.state = "device"
                for step in range(6):  # backend stays down: keep retrying, never open the app
                    now[0] = app.next_try
                    app.tick()
                    self.assertIn("Phone service unavailable", app.lines[-1])
                    self.assertLessEqual(app.next_try - now[0], 10)
                self.assertEqual(launches(), 1)
                self.assertEqual(app.starts, 1)
                backend[0] = True  # phone backend restarted from Termux
                now[0] = app.next_try
                app.tick()
                finish_preflight(app)
            self.assertTrue(app.online)
            self.assertEqual(app.starts, 2)
            self.assertEqual(launches(), 2)
            self.assertEqual(len(fake.forwards), 1)

    def test_forwards_cleared_while_device_stays_listed_are_rebuilt(self):
        """adbd restarted but the adb server never saw the device leave."""
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767, 18768]
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.keys.save_first_allow(bytes(range(32)))
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", return_value=True):
                app.tick()
                finish_preflight(app)
                self.assertEqual(app.starts, 1)
                fake.forwards.clear()
                now[0] = 101.0
                app.tick()
                self.assertFalse(app.online)
                self.assertIn("Phone link interrupted", app.lines[-1])
                now[0] = app.next_try
                app.tick()
                finish_preflight(app)
            self.assertTrue(app.online)
            self.assertEqual(app.starts, 2)
            self.assertEqual(list(fake.forwards), [18768])

    def test_rejected_saved_key_never_reenrols(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767]
            app = app_fixture(directory, fake, [100.0])
            key = bytes(range(32))
            app.keys.save_first_allow(key)
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=False), \
                    self.assertRaisesRegex(link.CompanionError, "owner recovery"):
                app._connect()
            app.bridge.remove_own_forward()
            self.assertEqual(app.keys.load(), key)
            self.assertFalse(any("nc" in args for args, _ in fake.calls))

    def test_model_server_down_retries_after_three_seconds(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767, 18768]
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.keys.save_first_allow(bytes(range(32)))
            available = [False]
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", side_effect=lambda url: available[0]), \
                    patch.object(link, "model_server_preflight", return_value=True):
                app.tick()
                self.assertFalse(app.online)
                self.assertEqual(app.next_try, 103.0)
                self.assertEqual(list(fake.forwards), [18767])
                self.assertIn("Local model server unavailable", app.lines[-1])
                available[0] = True
                now[0] = 102.0
                app.tick()
                self.assertEqual(app.starts, 0)
                now[0] = 103.0
                app.tick()
                finish_preflight(app)
                self.assertTrue(app.online)
                self.assertEqual(app.starts, 1)
                available[0] = False
                now[0] = 104.0
                app.tick()
            self.assertFalse(app.online)
            self.assertEqual(fake.forwards, {})
            self.assertIn("Local model server unavailable", app.lines[-1])

    def test_all_forbidden_pc_ports_are_removed(self):
        for forbidden in sorted(link.FORBIDDEN_PC_PORTS):
            with self.subTest(port=forbidden):
                fake = FakeAdb()
                fake.state = "device"
                fake.assigned = [forbidden, 18767]
                bridge = link.AdbBridge("fake-adb", "PHONE", runner=fake,
                                        owner_checker=lambda port, adb: True)
                self.assertEqual(bridge.create_forward(), 18767)
                self.assertNotIn(forbidden, fake.forwards)

    def test_provisional_forward_is_cleaned_after_list_failure(self):
        fake = FakeAdb()
        fake.state = "device"
        fake.assigned = [18767]
        fake.fail_list_once = True
        bridge = link.AdbBridge("fake-adb", "PHONE", runner=fake,
                                owner_checker=lambda port, adb: True)
        with self.assertRaises(link.RetryLater):
            bridge.create_forward()
        self.assertEqual(fake.forwards, {})
        self.assertIsNone(bridge.provisional_port)

    def test_auto_serial_selects_usb_when_wireless_duplicate_is_present(self):
        def runner(lines):
            return lambda command, **kwargs: SimpleNamespace(
                returncode=0, stdout=("List of devices attached\n" + lines).encode(), stderr=b"")

        usb = "EXAMPLE0001 device usb:1-1 product:flip6\n"
        mdns = "adb-EXAMPLE0001-xxxx._adb-tls-connect._tcp device product:flip6\n"
        tcp = "192.0.2.2:5555 device product:flip6\n"
        for lines in (usb, usb + mdns, mdns + usb, usb + tcp,
                      mdns + tcp + usb + mdns, tcp + usb + tcp,
                      "OTHER unauthorized usb:1-2\n" + usb + "OFF offline usb:1-3\n",
                      "emulator-5554 device usb:1-2\n" + usb):
            with self.subTest(lines=lines):
                self.assertEqual(link.select_serial("fake-adb", runner(lines)), "EXAMPLE0001")

    def test_auto_serial_waits_for_empty_and_refuses_zero_or_multiple_usb_phones(self):
        def runner(lines):
            return lambda command, **kwargs: SimpleNamespace(
                returncode=0, stdout=("List of devices attached\n" + lines).encode(), stderr=b"")

        self.assertIsNone(link.select_serial("fake-adb", runner("")))
        self.assertIsNone(link.select_serial("fake-adb", runner(
            "ONE unauthorized usb:1-1\nTWO offline usb:1-2\n")))
        for lines in (
            "192.0.2.2:5555 device\n",
            "adb-EXAMPLE0001-xxxx._adb-tls-connect._tcp device\n",
            "ONE device\nTWO device\n",
            "emulator-5554 device usb:1-1\n",
            "192.0.2.2:5555 device usb:1-1\n",
            "ONE device usb:1-1\nTWO device usb:1-2\n",
        ):
            with self.subTest(lines=lines), self.assertRaises(link.CompanionError):
                link.select_serial("fake-adb", runner(lines))
        self.assertEqual(link.select_serial("fake-adb", runner(
            "ONE device usb:1-1\nemulator-5554 device usb:1-2\n")), "ONE")

    def test_explicit_serial_avoids_inventory_and_rejects_network_transport(self):
        with patch.object(link, "select_serial", side_effect=AssertionError("inventory used")):
            args = link.arguments(["--serial", "EXAMPLE0001", "--model", "local"])
        self.assertEqual(args.serial, "EXAMPLE0001")
        with contextlib.redirect_stderr(io.StringIO()):
            for serial in ("192.0.2.2:5555", "emulator-5554",
                           "adb-EXAMPLE0001-xxxx._adb-tls-connect._tcp"):
                with self.subTest(serial=serial), self.assertRaises(SystemExit):
                    link.arguments(["--serial", serial, "--model", "local"])

    def test_main_waits_two_seconds_per_empty_usb_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = io.StringIO()
            with contextlib.redirect_stdout(output), \
                    patch.object(link.gpu_link_discover, "discover", return_value=[]), \
                    patch.object(link, "resolve_launch_adb", side_effect=lambda adb, runner=None: adb), \
                    patch.object(link, "select_serial", side_effect=[None, None, "PHONE"]) as select, \
                    patch.object(link.time, "sleep") as sleep, \
                    patch.object(link, "Companion") as companion_type:
                companion_type.return_value.cleanup_ok = True
                result = link.main(["--headless", "--model", "local", "--key-dir", directory])
            self.assertEqual(result, 0)
            self.assertEqual(select.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual([call.args for call in sleep.call_args_list], [(2,), (2,)])
            self.assertEqual(output.getvalue().count("Waiting for exactly one authorized USB phone"), 1)

    def test_main_refuses_multiple_usb_phones_with_one_line(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), \
                patch.object(link.gpu_link_discover, "discover", return_value=[]), \
                patch.object(link, "resolve_launch_adb", side_effect=lambda adb, runner=None: adb), \
                patch.object(link, "select_serial", side_effect=link.CompanionError(
                    "More than one authorized USB phone is present; pass --serial")):
            self.assertEqual(link.main(["--headless", "--model", "local"]), 2)
        self.assertEqual(output.getvalue().splitlines(), [
            "GPU Link: More than one authorized USB phone is present; pass --serial"])

    def test_one_token_preflight_uses_exact_route_and_model(self):
        class Response:
            def __init__(self, lines, content_type="text/event-stream", status=200):
                self.lines = iter(lines)
                self.content_type = content_type
                self.status = status

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return None

            def getheader(self, name, default=None):
                if name == "Content-Type":
                    return self.content_type
                return default

            def readline(self, size):
                return next(self.lines, b"")

        class Connection:
            def __init__(self, response):
                self.response = response
                self.request_args = None
                self.closed = False
                self.read_timeout = None
                self.read_timeouts = []
                self.sock = SimpleNamespace(settimeout=self.settimeout,
                                            shutdown=lambda how: None)

            def connect(self):
                pass

            def settimeout(self, value):
                self.read_timeout = value
                self.read_timeouts.append(value)

            def request(self, *args):
                self.request_args = args

            def getresponse(self):
                return self.response

            def close(self):
                self.closed = True

        class StalledResponse(Response):
            def readline(self, size):
                line = next(self.lines, None)
                if line is None:
                    raise TimeoutError("stream stalled")
                return line

        server = "http://127.0.0.1:9001/v1/chat/completions?slot=stage"
        success = Connection(Response([
            b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"length"}], "model":"stage-model"}\n',
            b'data: [DONE]\n',
        ]))
        with patch.object(link.http.client, "HTTPConnection", return_value=success) as factory:
            self.assertTrue(link.model_server_preflight(server, "stage-model"))
        factory.assert_called_once_with("127.0.0.1", 9001, timeout=2)
        method, target, payload, headers = success.request_args
        self.assertEqual((method, target), ("POST", "/v1/chat/completions?slot=stage"))
        self.assertEqual(headers["Accept"], "text/event-stream")
        body = json.loads(payload)
        self.assertEqual(body["model"], "stage-model")
        self.assertEqual(body["max_tokens"], 1)
        self.assertTrue(body["stream"])
        self.assertEqual(body["stream_options"], {"include_usage": True})
        self.assertEqual(success.read_timeouts, [90, 10])
        self.assertTrue(success.closed)

        for response in (Response([b'data: {"choices":[],"model":"stage-model","usage":{"total_tokens":1}}\n',
                                   b'data: [DONE]\n']),
                         Response([b'data: [DONE]\n']),
                         Response([b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"length"}],"model":"wrong-model"}\n',
                                   b'data: [DONE]\n']),
                         Response([b'data: {"usage":{},"model":"wrong-model"}\n',
                                   b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"model":"stage-model"}\n',
                                   b'data: [DONE]\n']),
                         Response([b'data: {"choices":null,"usage":{},"model":"stage-model"}\n',
                                   b'data: [DONE]\n']),
                         Response([b'data: {"choices":[{"delta":{},"finish_reason":"stop"}],"model":"stage-model"}\n',
                                   b'data: [DONE]\n']),
                         Response([b'data: {"unexpected":"payload"}\n',
                                   b'data: [DONE]\n']),
                         Response([b'data: {"choices":[{"index":0,"delta":{"content":"O"}}],"model":"stage-model"}\n',
                                   b'data: [DONE]\n']),
                         Response([b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"model":"stage-model"}\n']),
                         StalledResponse([
                             b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"length"}],"model":"stage-model"}\n',
                         ]),
                         Response([b'data: not-json\n']),
                         Response([b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"length"}],"model":"stage-model"}\n',
                                   b'data: [DONE]\n'], content_type="application/json"),
                         Response([b'data: [DONE]\n'], status=500)):
            with self.subTest(response=response), \
                    patch.object(link.http.client, "HTTPConnection",
                                 return_value=Connection(response)):
                self.assertFalse(link.model_server_preflight(server, "stage-model"))

        stop = Connection(Response([
            b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],"model":"stage-model"}\n',
            b'data: [DONE]\n',
        ]))
        with patch.object(link.http.client, "HTTPConnection", return_value=stop):
            self.assertTrue(link.model_server_preflight(server, "stage-model"))

        # Reported LM Studio payload; the omitted fields in the report are a valid id here.
        gemma = Connection(Response([
            (b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"length"}], '
             b'"model":"gemma-4-26b", "id":"chatcmpl-host-test"}\n'),
            b'data: [DONE]\n',
        ]))
        with patch.object(link.http.client, "HTTPConnection", return_value=gemma):
            self.assertTrue(link.model_server_preflight(server, "gemma-4-26b"))

    def test_failed_preflight_retries_before_worker_is_ready(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767, 18768]
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.args.no_launch = False
            app.keys.save_first_allow(bytes(range(32)))
            valid = [False]
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight",
                                 side_effect=lambda server, model, **kwargs: valid[0]) as preflight:
                for delay in (3, 6, 10, 10, 10):
                    app.tick()
                    finish_preflight(app)
                    self.assertFalse(app.online)
                    self.assertEqual(app.starts, 0)
                    self.assertEqual(app.next_try - now[0], delay)
                    self.assertEqual(list(fake.forwards), [18767])
                    self.assertIn("one-token check", app.lines[-1])
                    now[0] = app.next_try
                valid[0] = True
                app.tick()
                finish_preflight(app)
                self.assertTrue(app.online)
                self.assertEqual(app.starts, 1)
                self.assertEqual(len(fake.forwards), 1)
                self.assertEqual(sum(args[2:5] == ["shell", "am", "start"]
                                     for args, _ in fake.calls), 1)
                self.assertEqual(preflight.call_count, 6)
            preflight.assert_called_with(link.DEFAULT_SERVER, "local", cancelled=ANY)

    def test_delayed_headers_and_first_event_allow_cold_model(self):
        chunk = (b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"length"}],'
                 b'"model":"gemma-4-26b"}\n\ndata: [DONE]\n\n')
        for delay_headers in (True, False):
            with self.subTest(delay_headers=delay_headers):
                entered, release = threading.Event(), threading.Event()
                class Response:
                    status = 200

                    def __init__(self):
                        self.lines = iter(chunk.splitlines(keepends=True))
                        self.first = True

                    def __enter__(self):
                        return self

                    def __exit__(self, *args):
                        pass

                    def getheader(self, name, default=None):
                        return "text/event-stream" if name == "Content-Type" else default

                    def readline(self, size, delaying=delay_headers,
                                 start=entered, unblock=release):
                        if self.first and not delaying:
                            self.first = False
                            start.set()
                            unblock.wait(4)
                        return next(self.lines, b"")

                class Connection:
                    def __init__(self, host, port, timeout):
                        self.connect_timeout = timeout
                        self.read_timeout = None
                        self.read_timeouts = []
                        self.sock = self
                        self.requests = []

                    def connect(self):
                        pass

                    def settimeout(self, timeout):
                        self.read_timeout = timeout
                        self.read_timeouts.append(timeout)

                    def request(self, *args):
                        self.requests.append(args)

                    def getresponse(self, delaying=delay_headers,
                                    start=entered, unblock=release):
                        if delaying:
                            start.set()
                            unblock.wait(4)
                        return Response()

                    def close(self):
                        pass

                connection = Connection("127.0.0.1", 9001, 2)
                result = []
                with patch.object(link.http.client, "HTTPConnection", return_value=connection):
                    client = threading.Thread(target=lambda output=result: output.append(link.model_server_preflight(
                        "http://127.0.0.1:9001/v1/chat/completions", "gemma-4-26b",
                        first_event_timeout=5)), daemon=True)
                    client.start()
                    self.assertTrue(entered.wait(2))
                    time.sleep(2.2)  # Longer than the TCP connect timeout.
                    self.assertTrue(client.is_alive())
                    release.set()
                    client.join(3)
                self.assertEqual(result, [True])
                self.assertEqual(connection.connect_timeout, 2)
                self.assertEqual(connection.read_timeouts, [5, 10])
                self.assertEqual(len(connection.requests), 1)
                self.assertEqual(json.loads(connection.requests[0][2])["model"], "gemma-4-26b")

    def test_preflight_wait_can_be_cancelled_after_header_ownership_changes(self):
        class Wire:
            def __init__(self):
                self.aborted = threading.Event()

            def settimeout(self, value):
                pass

            def shutdown(self, how):
                self.aborted.set()

            def close(self):
                pass

        class Connection:
            def __init__(self):
                self.sock = Wire()
                self.wire = self.sock
                self.requested = threading.Event()

            def connect(self):
                pass

            def request(self, *args):
                self.requested.set()

            def getresponse(self):
                self.sock = None  # http.client can transfer the socket to the response.
                self.wire.aborted.wait(2)
                raise OSError("cancelled")

            def close(self):
                pass

        connection = Connection()
        cancelled = threading.Event()
        result = []
        with patch.object(link.http.client, "HTTPConnection", return_value=connection):
            worker = threading.Thread(target=lambda: result.append(link.model_server_preflight(
                "http://127.0.0.1:9001/v1/chat/completions", "stage-model",
                cancelled=cancelled.is_set, first_event_timeout=5)), daemon=True)
            worker.start()
            self.assertTrue(connection.requested.wait(2))
            cancelled.set()
            worker.join(2)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, [False])
        self.assertTrue(connection.wire.aborted.is_set())

    def test_first_event_deadline_extends_for_finish_and_done(self):
        class Response:
            status = 200

            def __init__(self):
                self.lines = iter([
                    (b'data: {"choices":[{"index":0,"delta":{},"finish_reason":"length"}],'
                     b'"model":"stage-model"}\n'),
                    b'data: [DONE]\n',
                ])

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def getheader(self, name, default=None):
                return "text/event-stream" if name == "Content-Type" else default

            def readline(self, size):
                time.sleep(0.35)
                return next(self.lines, b"")

        class Connection:
            def __init__(self):
                self.sock = SimpleNamespace(settimeout=lambda value: None,
                                            shutdown=lambda how: None,
                                            close=lambda: None)

            def connect(self):
                pass

            def request(self, *args):
                pass

            def getresponse(self):
                return Response()

            def close(self):
                pass

        with patch.object(link.http.client, "HTTPConnection", return_value=Connection()):
            self.assertTrue(link.model_server_preflight(
                "http://127.0.0.1:9001/v1/chat/completions", "stage-model",
                first_event_timeout=0.6, completion_timeout=0.6))

    def test_preflight_first_event_deadline_expires(self):
        class Connection:
            def __init__(self):
                self.aborted = threading.Event()
                self.sock = self

            def connect(self):
                pass

            def settimeout(self, value):
                pass

            def request(self, *args):
                pass

            def getresponse(self):
                self.aborted.wait(2)
                raise OSError("deadline")

            def shutdown(self, how):
                self.aborted.set()

            def close(self):
                pass

        connection = Connection()
        with patch.object(link.http.client, "HTTPConnection", return_value=connection):
            self.assertFalse(link.model_server_preflight(
                "http://127.0.0.1:9001/v1/chat/completions", "stage-model",
                first_event_timeout=0.2))
        self.assertTrue(connection.aborted.is_set())

    def test_cold_preflight_is_single_flight_and_cancelled_on_detach(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767, 18768]
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.args.no_launch = False
            app.keys.save_first_allow(bytes(range(32)))
            entered, release = threading.Event(), threading.Event()
            requests = []

            def preflight(server, model, cancelled):
                requests.append((server, model))
                entered.set()
                while not release.wait(0.01):
                    if cancelled():
                        return False
                return not cancelled()

            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", side_effect=preflight):
                app.tick()
                self.assertTrue(entered.wait(2))
                self.assertEqual(app.lines[-1], "Warming model")
                app.tick()
                app.tick()
                self.assertEqual(len(requests), 1)
                self.assertEqual(sum(args[2:5] == ["shell", "am", "start"]
                                     for args, _ in fake.calls), 1)
                self.assertEqual(len(fake.forwards), 1)
                fake.state = "unauthorized"
                app.tick()
                self.assertTrue(app.preflight_done.wait(2))
                self.assertEqual(fake.forwards, {})
                self.assertEqual(app.starts, 0)
                self.assertIn("Phone disconnected; waiting to reconnect", app.lines[-1])
                self.assertEqual(app.next_try, 101.0)
                self.assertEqual(app.retry_delay, 3)
                release.set()
                app.tick()
                fake.state = "device"
                now[0] = 104.0
                app.tick()
                finish_preflight(app)
                self.assertEqual(len(requests), 2)
                self.assertEqual(sum(args[2:5] == ["shell", "am", "start"]
                                     for args, _ in fake.calls), 2)
                self.assertTrue(app.online)


    def test_successful_preflight_with_lost_forward_does_not_blame_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767, 18768]
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.keys.save_first_allow(bytes(range(32)))
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", return_value=True):
                app.tick()
                self.assertEqual(app.lines[-1], "Warming model")
                fake.forwards.clear()
                finish_preflight(app)
                self.assertFalse(app.online)
                self.assertEqual(app.starts, 0)
                self.assertEqual(app.lines[-1], "Phone link interrupted; reconnecting")
                self.assertNotIn("Local model or chat route failed", "".join(app.lines))
                self.assertEqual(app.next_try, 101.0)
                now[0] = 101.0
                app.tick()
                if not app.online:
                    finish_preflight(app)
            self.assertTrue(app.online)
            self.assertEqual(app.starts, 1)

    def test_failed_preflight_with_lost_forward_does_not_blame_the_model(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767, 18768]
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.keys.save_first_allow(bytes(range(32)))
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", return_value=False):
                app.tick()
                self.assertEqual(app.lines[-1], "Warming model")
                fake.forwards.clear()
                finish_preflight(app)
                self.assertFalse(app.online)
                self.assertEqual(app.starts, 0)
                self.assertEqual(app.lines[-1], "Phone link interrupted; reconnecting")
                self.assertNotIn("Local model or chat route failed", "".join(app.lines))
                self.assertEqual(app.next_try, 101.0)

    def test_lost_forward_during_warmup_cancels_preflight(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767, 18768]
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.keys.save_first_allow(bytes(range(32)))
            entered, release = threading.Event(), threading.Event()

            def preflight(server, model, cancelled):
                entered.set()
                while not release.wait(0.01):
                    if cancelled():
                        return False
                return not cancelled()

            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", side_effect=preflight):
                app.tick()
                self.assertTrue(entered.wait(2))
                self.assertEqual(app.lines[-1], "Warming model")
                fake.forwards.clear()
                app.tick()
                self.assertTrue(app.preflight_done.wait(2))
                self.assertEqual(app.lines[-1], "Phone link interrupted; reconnecting")
                self.assertEqual(app.starts, 0)
                self.assertEqual(app.next_try, 101.0)
                release.set()
                now[0] = 101.0
                app.tick()
                self.assertNotIn("Local model or chat route failed", "".join(app.lines))
                if not app.online:
                    finish_preflight(app)
            self.assertTrue(app.online)
            self.assertEqual(app.starts, 1)

    def test_detach_during_backoff_resets_the_retry_timer(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767, 18768]
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.keys.save_first_allow(bytes(range(32)))
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", return_value=False):
                app.tick()
                finish_preflight(app)
                self.assertFalse(app.online)
                self.assertGreater(app.next_try, now[0])
                self.assertIn("Local model or chat route failed", app.lines[-1])
                fake.state = "unauthorized"
                app.tick()
                self.assertIn("Phone disconnected; waiting to reconnect", app.lines[-1])
                self.assertEqual(app.next_try, 101.0)
                self.assertEqual(app.retry_delay, 3)
            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", return_value=True):
                fake.state = "device"
                now[0] = 101.0  # after the one-second floor; inside the old long backoff
                app.tick()
                finish_preflight(app)
            self.assertTrue(app.online)
            self.assertEqual(app.starts, 1)

    def test_stop_cancels_warmup_without_starting_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = [18767]
            app = app_fixture(directory, fake, [100.0])
            app.keys.save_first_allow(bytes(range(32)))
            entered = threading.Event()

            def preflight(server, model, cancelled):
                entered.set()
                while not cancelled():
                    time.sleep(0.01)
                return False

            with patch.object(link, "PC", FakePC), \
                    patch.object(link, "authenticated_idle", return_value=True), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", side_effect=preflight):
                app.tick()
                self.assertTrue(entered.wait(2))
                app.stop()
            self.assertFalse(app.running)
            self.assertEqual(app.starts, 0)
            self.assertEqual(fake.forwards, {})
            self.assertTrue(app.cleanup_ok)

    def test_worker_stop_fences_fetch_and_post(self):
        stop = threading.Event()
        calls = []

        class FakeWorkerPC:
            epoch = b"epoch"

            def status(self, *args):
                calls.append("status")
                stop.set()
                return 200, {"cancel": None}

            def send(self, *args):
                calls.append("send")
                return 204, {}

        worker = link.StandIn(FakeWorkerPC(), emit=lambda line: None, clock=lambda: 0)
        worker.stop_event = stop
        with self.assertRaises(StopRequested):
            worker.step()
        self.assertEqual(calls, ["status"])

        stop.clear()
        worker.job = {"lease": "0" * 32}
        worker.offset = 0
        worker.source = SimpleNamespace(snapshot=lambda: (stop.set() or b"text", True, "stop", 1, False),
                                        close=lambda: None)
        with self.assertRaises(StopRequested):
            worker._post()
        self.assertEqual(calls, ["status"])

    def test_missing_tk_falls_back_to_headless_and_sigterm_stops(self):
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(link.gpu_link_discover, "discover", return_value=[]), \
                patch.object(link, "resolve_launch_adb", side_effect=lambda adb, runner=None: adb), \
                patch.object(link, "select_serial", return_value="PHONE"), \
                patch.dict(sys.modules, {"tkinter": None}), \
                patch.object(link, "Companion") as companion_type:
            app = companion_type.return_value
            app.run.side_effect = lambda: signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            self.assertEqual(link.main(["--model", "local", "--key-dir", directory]), 0)
            self.assertTrue(companion_type.call_args.kwargs["headless"])
            app.stop.assert_called_once()

    def test_instance_guard_refuses_second_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            first = link.InstanceGuard(Path(directory), "PHONE")
            try:
                with self.assertRaises(link.CompanionError):
                    link.InstanceGuard(Path(directory), "PHONE")
            finally:
                first.close()
            third = link.InstanceGuard(Path(directory), "PHONE")
            third.close()

    def test_reset_pairing_is_stopped_only_and_scoped_to_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            first = link.KeyStore(root, "PHONE")
            other = link.KeyStore(root, "OTHER")
            first.save_first_allow(bytes(range(32)))
            other.save_first_allow(bytes(reversed(range(32))))
            running = link.InstanceGuard(root, "PHONE")
            try:
                output = io.StringIO()
                with contextlib.redirect_stderr(output), \
                        patch.object(link, "select_serial", side_effect=AssertionError("adb used")):
                    self.assertEqual(link.main(["--reset-pairing", "--serial", "PHONE",
                                                "--key-dir", directory]), 2)
                self.assertIn("already running", output.getvalue())
                self.assertIsNotNone(first.load())
            finally:
                running.close()
            output = io.StringIO()
            with contextlib.redirect_stdout(output), \
                    patch.object(link, "select_serial", side_effect=AssertionError("adb used")):
                self.assertEqual(link.main(["--reset-pairing", "--serial", "PHONE",
                                            "--key-dir", directory]), 0)
            self.assertIn("Saved pairing removed", output.getvalue())
            self.assertIsNone(first.load())
            self.assertIsNotNone(other.load())
            first.save_first_allow(bytes(range(32)))
            original_reset = link.KeyStore.reset

            def check_companion_cannot_start_during_reset(store):
                with self.assertRaises(link.CompanionError):
                    link.InstanceGuard(root, "PHONE")
                return original_reset(store)

            with contextlib.redirect_stdout(io.StringIO()), \
                    patch.object(link.KeyStore, "reset", check_companion_cannot_start_during_reset):
                self.assertEqual(link.main(["--reset-pairing", "--serial", "PHONE",
                                            "--key-dir", directory]), 0)
            self.assertIsNone(first.load())
            with contextlib.redirect_stdout(io.StringIO()), \
                    patch.object(link, "select_serial", side_effect=AssertionError("adb used")):
                self.assertEqual(link.main(["--reset-pairing", "--serial", "PHONE",
                                            "--key-dir", directory]), 0)
            after = link.InstanceGuard(root, "PHONE")
            after.close()

    def test_reset_pairing_requires_explicit_usb_serial(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                link.arguments(["--reset-pairing"])
            with self.assertRaises(SystemExit):
                link.arguments(["--reset-pairing", "--serial", "192.0.2.5:5555"])

    def test_enrol_reply_is_bounded_and_requires_full_body(self):
        body = b'{"state":"pending"}'
        response = (b"HTTP/1.1 202 Accepted\r\nContent-Length: 19\r\n"
                    b"Connection: close\r\n\r\n" + body)
        self.assertEqual(link.parse_enrol_reply(response), (202, "pending"))
        with self.assertRaises(link.CompanionError):
            link.parse_enrol_reply(response[:-1])

    def test_grant_timer_starts_on_unplug_not_worker_failure(self):
        now = [100.0]
        attached = [True]
        app = link.Companion.__new__(link.Companion)
        app.args = SimpleNamespace(server="http://127.0.0.1:9001/v1/chat/completions")
        app.running = True
        app.clock = lambda: now[0]
        app.events = queue.SimpleQueue()
        app.status = SimpleNamespace(set=lambda message: None)
        app.root = SimpleNamespace(after=lambda delay, callback: None)
        app.bridge = SimpleNamespace(authorized=lambda: attached[0],
                                     forward_present=lambda: True,
                                     remove_own_forward=lambda: None)
        app.online = True
        app.worker = None
        app.worker_stop = None
        app.preflight_thread = None
        app.preflight_done = None
        app.preflight_cancel = None
        app.session_pc = None
        app.retry_delay = 3
        app.granted = True
        app.detached_at = None
        app.blocked_until_detach = False
        app.next_try = 1000.0
        with patch.object(link, "model_server_listening", return_value=True):
            app.tick()  # Worker exited, but cable is still attached.
            self.assertIsNone(app.detached_at)
            attached[0] = False
            now[0] = 101.0
            app.tick()
            self.assertEqual(app.detached_at, 101.0)
            now[0] = 220.0
            app.tick()
            self.assertTrue(app.granted)
            now[0] = 221.0
            attached[0] = True
            app.next_try = 1000.0
            app.tick()
            self.assertFalse(app.granted)


class FanoutTests(unittest.TestCase):
    def test_old_phone_rejection_falls_back_to_main_after_trust_proof(self):
        class OldPC:
            host, port, key, label = "127.0.0.1", 18767, b"K" * 32, "Test PC"
            def __init__(self):
                self.calls = 0
            def send(self, *_args):
                self.calls += 1
                raise link.RejectedError("old phone refused unknown body")

        app = link.Companion.__new__(link.Companion)
        app.args = SimpleNamespace(server="http://127.0.0.1:1235/v1/chat/completions", model="main",
                                   extra_models=[{"id": "extra", "label": "Extra", "maker": "Maker", "gpu": None}])
        app.running = True
        app.events = queue.SimpleQueue()
        app.worker = app.worker_stop = None
        pc, rates = OldPC(), []

        def standin(*_args, **kwargs):
            rates.append(kwargs["rate"])
            return SimpleNamespace(run=lambda _stop: None)

        with patch.object(link, "authenticated_idle", return_value=True) as trust, \
                patch.object(link, "StandIn", side_effect=standin):
            app._start_worker(pc)
            app.worker.join(2)
        self.assertEqual(pc.calls, 2)
        trust.assert_called_once_with(pc)
        self.assertEqual(rates, [4])

    def test_stream_rejects_a_different_declared_model(self):
        source = ServerSource.__new__(ServerSource)
        source.model = "expected"
        with self.assertRaises(ToolError):
            source._event({"model": "wrong", "choices": []})

    def test_three_workers_post_from_their_own_acknowledged_offsets(self):
        partials = ["a", "café", "longer third"]
        posts = []

        class PC:
            epoch = b"epoch"
            def __init__(self, pane, partial):
                self.pane, self.partial = pane, partial
            def send(self, method, target, body=b""):
                if method == "GET":
                    return 200, {"lease": self.pane * 32, "question": "One question",
                                 "partial": self.partial, "model_id": "model/" + self.pane}
                post = proto.loads(body, proto.TEXT_BODY_LIMIT)
                posts.append((self.pane, post))
                return 200, {"acked": post["offset"] + len(post["text"].encode())}
            def status(self, *_args):
                return 200, {"cancel": None}

        class Source:
            def __init__(self, job):
                self.data = job["partial"].encode() + b"!"
            def snapshot(self):
                return self.data, True, "stop", 1, False
            def close(self):
                pass

        workers = [link.StandIn(PC(str(index + 1), partial), Source, rate=1,
                                emit=lambda _line: None, clock=lambda: 100)
                   for index, partial in enumerate(partials)]
        for worker in workers:
            worker._work()
        self.assertEqual([worker.offset for worker in workers], [len(partial.encode()) for partial in partials])
        for worker in workers:
            worker._post()
        self.assertEqual([post["offset"] for _, post in posts], [len(partial.encode()) for partial in partials])
        self.assertTrue(all(post["text"] == "!" and post["done"] for _, post in posts))

    def test_slow_extra_preflight_stays_warming_until_retry_succeeds(self):
        calls, checked = [], set()

        def preflight(_url, _model, cancelled, retry_on_timeout):
            self.assertTrue(retry_on_timeout)
            self.assertFalse(cancelled())
            calls.append(1)
            return None if len(calls) == 1 else True

        class Source:
            def __init__(self, *_args):
                pass
            def snapshot(self):
                return b"ready", True, "stop", 1, False
            def close(self):
                pass

        with patch.object(link, "model_server_preflight", side_effect=preflight), \
                patch.object(link, "ServerSource", Source):
            source = link.LazyServerSource({"question": "q", "partial": ""}, "http://127.0.0.1:1235/v1",
                                           "extra", checked, threading.Lock())
            try:
                deadline = time.monotonic() + 3
                while len(calls) < 1 and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(source.warming)
                self.assertFalse(source.snapshot()[-1])
                while source.warming and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertFalse(source.warming)
                self.assertEqual(source.snapshot()[0], b"ready")
                self.assertEqual(len(calls), 2)
                self.assertIn("extra", checked)
            finally:
                source.close()

    def test_extra_model_flags_file_and_protocol_reply(self):
        args = link.arguments(["--model", "main", "--extra-model", "qwen/qwen3-4b:Qwen 3 4B:Qwen",
                               "--extra-model", "lfm3-1.7b:LFM 3:Liquid AI"])
        self.assertEqual([item["id"] for item in args.extra_models], ["qwen/qwen3-4b", "lfm3-1.7b"])
        self.assertEqual([item["gpu"] for item in args.extra_models], [None, None])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "models.json"
            path.write_text(json.dumps({"models": [{"id": "vendor/model", "label": "Model",
                                                    "maker": "Maker"}]}))
            parsed = link.arguments(["--model", "main", "--models-file", str(path)])
            self.assertEqual(parsed.extra_models[0]["gpu"], None)
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                link.arguments(["--model", "main", "--extra-model", "bad"])
            with self.assertRaises(SystemExit):
                link.arguments(["--model", "main", "--extra-model", "same:A:B",
                                "--extra-model", "same:C:D"])
            with self.assertRaises(SystemExit):
                link.arguments(["--model", "main", "--extra-model", "main:Main again:Maker"])
        lease = b"L" * 16
        body = proto.extra_work_reply(lease, "qwen/qwen3-4b", "Question", "partial")
        self.assertEqual(checked_reply("/v1/lanes/g1/work?wait=0", 200, body)["model_id"], "qwen/qwen3-4b")
        self.assertEqual(checked_reply("/v1/lanes/g1/work?wait=0", 204, b""), {})

    def test_three_fake_lm_studio_streams_freeze_and_resume(self):
        models = ["qwen/qwen3-4b", "lfm3-1.7b", "vendor/third"]
        lock = threading.Lock()
        requests, active = [], [0, 0]
        case = self

        class Socket:
            def __init__(self):
                self.closed = threading.Event()

            def settimeout(self, _timeout):
                pass

            def shutdown(self, *_args):
                self.closed.set()

            def close(self):
                self.closed.set()

        def event(model, piece, finish=None):
            payload = {"model": model, "choices": [{"index": 0, "delta": {"content": piece},
                                                     "finish_reason": finish}]}
            return b"data: " + json.dumps(payload).encode() + b"\n\n"

        class Response:
            status = 200

            def __init__(self, body, sock):
                self.sock = sock
                self.initial_stream = body.get("max_tokens") != 1 and not any(
                    message.get("role") == "assistant" for message in body["messages"])
                model = body["model"]
                if body.get("max_tokens") == 1:
                    self.lines = iter([event(model, "OK", "stop"), b"data: [DONE]\n\n"])
                elif self.initial_stream:
                    with lock:
                        active[0] += 1
                        active[1] = max(active[1], active[0])
                    self.lines = iter([event(model, "first-" + model)])
                else:
                    self.lines = iter([event(model, "tail-" + model, "stop"), b"data: [DONE]\n\n"])

            def getheader(self, name, default=None):
                return "text/event-stream" if name == "Content-Type" else default

            def readline(self, _limit):
                line = next(self.lines, None)
                if line is not None:
                    return line
                if self.initial_stream:
                    self.sock.closed.wait(5)
                return b""

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                if self.initial_stream:
                    with lock:
                        active[0] -= 1

        class Connection:
            def __init__(self, host, port, timeout):
                case.assertEqual((host, port, timeout), ("127.0.0.1", 38123, 2))
                self.sock = Socket()

            def connect(self):
                pass

            def request(self, method, target, raw, _headers):
                case.assertEqual((method, target), ("POST", "/v1/chat/completions"))
                self.body = json.loads(raw)
                case.assertIn(self.body["model"], models)
                with lock:
                    requests.append(self.body)

            def getresponse(self):
                return Response(self.body, self.sock)

            def close(self):
                self.sock.close()

        url = "http://127.0.0.1:38123/v1/chat/completions"
        checked, checked_lock = set(), threading.Lock()
        sources = []
        try:
            with patch.object(link.http.client, "HTTPConnection", Connection), \
                    patch.dict(os.environ, {"OPOS_GPU_LINK_REASONING_EFFORT": "none", "OPOS_GPU_LINK_GUARD": "0"}):
                sources = [link.LazyServerSource({"question": "One question", "partial": ""}, url,
                                                 model, checked, checked_lock) for model in models]
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if all(source.snapshot()[0] == ("first-" + model).encode()
                           for source, model in zip(sources, models)):
                        break
                    time.sleep(0.02)
                self.assertEqual([source.snapshot()[0].decode() for source in sources],
                                 ["first-" + model for model in models])
                self.assertEqual(active[1], 3)
                sources[0].close()
                self.assertTrue(sources[0].snapshot()[1])
                self.assertTrue(all(not source.snapshot()[1] for source in sources[1:]))
                for source in sources:
                    source.close()  # Pull the USB link: each lane keeps its acknowledged prefix.
                self.assertEqual(active[0], 0)
                sources = [link.LazyServerSource({"question": "One question", "partial": "first-" + model},
                                                 url, model, checked, checked_lock) for model in models]
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    if all(source.snapshot()[1] for source in sources):
                        break
                    time.sleep(0.02)
                self.assertEqual([source.snapshot()[0].decode() for source in sources],
                                 ["first-" + model + "tail-" + model for model in models])
                self.assertTrue(all(source.snapshot()[1] for source in sources))
            with lock:
                self.assertTrue(all(request.get("reasoning_effort") == "none" for request in requests))
                resumed = [request for request in requests if any(
                    message.get("role") == "assistant" for message in request.get("messages", []))]
                preflights = [request for request in requests if request.get("max_tokens") == 1]
            self.assertEqual(len(preflights), 3)
            self.assertEqual({request["model"] for request in preflights}, set(models))
            self.assertEqual({request["model"] for request in resumed}, set(models))
            self.assertEqual({message["content"] for request in resumed for message in request["messages"]
                              if message.get("role") == "assistant"},
                             {"first-" + model for model in models})
        finally:
            for source in sources:
                source.close()


class R23WorkerLifecycleTests(unittest.TestCase):
    """Neon r22 review findings 1, 2 and 4: lane_workers, shared stop deadline, extra_checked."""

    MODELS = ({"id": "m-one", "label": "One", "maker": "Maker", "gpu": None},
              {"id": "m-two", "label": "Two", "maker": "Maker", "gpu": None},
              {"id": "m-three", "label": "Three", "maker": "Maker", "gpu": None})

    class AdvertisingPC:
        host, port, key, label = "127.0.0.1", 18767, b"K" * 32, "Test PC"
        epoch = None
        known_epoch = None
        on_new_epoch = None

        def __init__(self, state=None):
            self.state = state if state is not None else {"epoch": b"\x01" * proto.EPOCH_BYTES, "advertise": 200}
            self.advertisements = 0

        def hello(self):
            previous = self.known_epoch
            self.epoch = self.known_epoch = self.state["epoch"]
            if previous is not None and previous != self.epoch and self.on_new_epoch is not None:
                self.on_new_epoch(self.epoch)

        def send(self, method, target, body=b"", signed=True):
            if target == "/v1/advertise":
                self.advertisements += 1
                if self.state["advertise"] != 200:
                    return self.state["advertise"], {"error": "refused"}
                return 200, {"accepted": len(json.loads(body)["models"])}
            raise AssertionError(f"unexpected phone call {method} {target}")

    @staticmethod
    def companion(models=None):
        app = link.Companion.__new__(link.Companion)
        app.args = SimpleNamespace(server="http://127.0.0.1:1235/v1/chat/completions", model="main",
                                   extra_models=list(models if models is not None else R23WorkerLifecycleTests.MODELS))
        app.running = True
        app.events = queue.SimpleQueue()
        app.worker = app.worker_stop = None
        return app

    @staticmethod
    def blocking_standin(*_args, **_kwargs):
        return SimpleNamespace(run=lambda stop: stop.wait(10))

    @staticmethod
    def wait_for(predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()

    def stop_everything(self, app):
        if app.worker_stop is not None:
            app.worker_stop.set()
        if app.worker is not None:
            app.worker.join(3)

    # --- finding 2: sequential joins ---
    def test_join_within_uses_one_shared_deadline(self):
        now = [0.0]

        class Slow:
            def __init__(self, cost):
                self.cost, self.timeouts = cost, []
            def is_alive(self):
                return True
            def join(self, timeout):
                self.timeouts.append(timeout)
                now[0] += min(timeout, self.cost)

        threads = [Slow(10), Slow(10), Slow(10), Slow(10)]
        link.join_within(threads, 6.0, clock=lambda: now[0])
        self.assertEqual(threads[0].timeouts, [6.0])
        for later in threads[1:]:
            self.assertEqual(later.timeouts, [0.0])  # budget already spent, no further waiting
        self.assertEqual(now[0], 6.0)

    def test_join_within_skips_current_dead_and_missing_threads(self):
        calls = []

        class T:
            def __init__(self, alive):
                self.alive = alive
            def is_alive(self):
                return self.alive
            def join(self, timeout):
                calls.append(timeout)

        me, dead = T(True), T(False)
        link.join_within([None, me, dead, T(True)], 1.0, skip=me)
        self.assertEqual(len(calls), 1)

    def test_stop_worker_with_stuck_lanes_is_bounded_by_one_budget(self):
        app = self.companion()
        release = threading.Event()
        stuck = [threading.Thread(target=release.wait, daemon=True) for _ in range(4)]
        for thread in stuck:
            thread.start()
        app.worker, app.worker_stop = stuck[0], threading.Event()
        app.lane_workers = tuple(stuck[1:])
        try:
            with patch.object(link, "WORKER_STOP_BUDGET", 0.4):
                started = time.monotonic()
                app._stop_worker()
                elapsed = time.monotonic() - started
            # Four stuck threads used to cost four sequential joins (1.6 s here); now one budget.
            self.assertLess(elapsed, 0.9)
            self.assertTrue(app.worker_stop.is_set())
            self.assertIsNotNone(app.worker)  # still alive, so it is not forgotten
        finally:
            release.set()
            for thread in stuck:
                thread.join(2)

    def test_stop_worker_reaps_everything_and_forgets_extra_checks(self):
        app = self.companion()
        app.extra_checked, app.extra_checked_lock = {"m-one", "m-two"}, threading.Lock()
        done = [threading.Thread(target=lambda: None) for _ in range(3)]
        for thread in done:
            thread.start()
            thread.join()
        app.worker, app.worker_stop, app.lane_workers = done[0], threading.Event(), tuple(done[1:])
        app._stop_worker()
        self.assertIsNone(app.worker)
        self.assertEqual(app.lane_workers, ())
        self.assertEqual(app.extra_checked, set())  # finding 4: no stale "already loaded" claims

    # --- finding 1: lane_workers publication ---
    def test_lane_threads_are_only_visible_once_started(self):
        app = self.companion()
        pc = self.AdvertisingPC()
        real_thread = threading.Thread

        class SlowStart(real_thread):
            def start(self):
                if self.name.startswith("opos-gpu-g"):
                    time.sleep(0.05)  # widen the old append-then-start window
                super().start()

        seen_dead = []
        sampling = threading.Event()

        def sample():
            while not sampling.is_set():
                if app.worker is not None and app.worker.is_alive():
                    lanes = tuple(getattr(app, "lane_workers", ()))
                    if any(not lane.is_alive() for lane in lanes):
                        seen_dead.append(lanes)
                    if lanes and not app._workers_alive():
                        seen_dead.append(lanes)
                time.sleep(0.0005)

        sampler = real_thread(target=sample, daemon=True)
        with patch.object(link.threading, "Thread", SlowStart), \
                patch.object(link, "StandIn", side_effect=self.blocking_standin):
            sampler.start()
            app._start_worker(pc)
            self.assertTrue(self.wait_for(lambda: len(app.lane_workers) == 3))
            time.sleep(0.1)
        sampling.set()
        sampler.join(1)
        self.assertEqual(seen_dead, [])
        self.assertTrue(app._workers_alive())
        self.stop_everything(app)

    def test_new_session_does_not_inherit_dead_lane_threads(self):
        app = self.companion()
        dead = threading.Thread(target=lambda: None)
        dead.start()
        dead.join()
        app.lane_workers = (dead,)
        pc = self.AdvertisingPC()
        entered, release = threading.Event(), threading.Event()
        original_send = pc.send

        def gated_send(*args, **kwargs):
            release.wait(3)  # hold the new worker so only the synchronous clear can explain the result
            return original_send(*args, **kwargs)

        pc.send = gated_send

        def standin(*_args, **_kwargs):
            return SimpleNamespace(run=lambda stop: (entered.set(), stop.wait(10)))

        with patch.object(link, "StandIn", side_effect=standin):
            app._start_worker(pc)
            self.assertNotIn(dead, app.lane_workers)  # cleared synchronously, before any thread runs
            release.set()
            self.assertTrue(entered.wait(3))
            self.assertTrue(self.wait_for(lambda: len(app.lane_workers) == 3))
            self.assertTrue(app._workers_alive())
        self.stop_everything(app)
        self.assertFalse(any(lane.is_alive() for lane in app.lane_workers))

    def test_stopped_session_never_publishes_its_lanes(self):
        app = self.companion()
        pc = self.AdvertisingPC()
        gate, in_send = threading.Event(), threading.Event()
        original_send = pc.send
        started = []
        real_thread = threading.Thread

        class Recording(real_thread):
            def start(self):
                started.append(self.name)
                super().start()

        def gated_send(*args, **kwargs):
            in_send.set()
            gate.wait(5)
            return original_send(*args, **kwargs)

        pc.send = gated_send
        with patch.object(link, "WORKER_STOP_BUDGET", 0.05), \
                patch.object(link.threading, "Thread", Recording), \
                patch.object(link, "StandIn", side_effect=self.blocking_standin):
            app._start_worker(pc)
            self.assertTrue(in_send.wait(3))
            worker = app.worker
            app._stop_worker()  # returns at the short budget while the worker is still advertising
            self.assertTrue(worker.is_alive())
            gate.set()
            worker.join(3)
            self.assertFalse(worker.is_alive())
        self.assertEqual(app.lane_workers, ())
        self.assertEqual([name for name in started if name.startswith("opos-gpu-g")], [])

    # --- finding 4: extra_checked ---
    def test_start_worker_forgets_previous_session_checks(self):
        app = self.companion()
        app.extra_checked, app.extra_checked_lock = {"m-one"}, threading.Lock()
        with patch.object(link, "StandIn", side_effect=self.blocking_standin):
            app._start_worker(self.AdvertisingPC())
            self.assertEqual(app.extra_checked, set())
        self.stop_everything(app)

    def test_failed_stream_discards_the_models_ready_mark(self):
        checked = {"extra"}

        class Failing:
            def __init__(self, *_args):
                pass
            def snapshot(self):
                return b"partial", False, "stop", 1, True
            def close(self):
                pass

        with patch.object(link, "model_server_preflight", return_value=True), \
                patch.object(link, "ServerSource", Failing):
            source = link.LazyServerSource({"question": "q", "partial": ""}, "http://127.0.0.1:1235/v1",
                                           "extra", checked, threading.Lock())
            try:
                self.assertTrue(self.wait_for(lambda: not source.warming))
                self.assertTrue(source.snapshot()[-1])
            finally:
                source.close()
        self.assertNotIn("extra", checked)

    # --- finding 4: phone backend restart => advertise again ---
    def test_phone_restart_readvertises_the_extra_models(self):
        app = self.companion()
        pc = self.AdvertisingPC()
        first, second, go = threading.Event(), threading.Event(), threading.Event()

        def standin(client, _source, **_kwargs):
            if client is not pc:
                return SimpleNamespace(run=lambda stop: stop.wait(10))

            def run(stop):
                pc.hello()
                first.set()
                go.wait(5)
                pc.hello()  # the companion reconnects and greets the restarted phone
                second.set()
                stop.wait(10)
            return SimpleNamespace(run=run)

        with patch.object(link, "StandIn", side_effect=standin):
            app._start_worker(pc)
            self.assertTrue(first.wait(3))
            self.assertEqual(pc.advertisements, 1)
            pc.hello()  # an unchanged epoch is not a restart
            self.assertEqual(pc.advertisements, 1)
            pc.state["epoch"] = b"\x02" * proto.EPOCH_BYTES  # the phone backend restarted
            go.set()
            self.assertTrue(second.wait(3))
            self.assertEqual(pc.advertisements, 2)
            self.assertTrue(app.worker.is_alive())
            self.assertFalse(app.worker_stop.is_set())
        self.stop_everything(app)

    def test_phone_restart_with_refused_readvertise_restarts_the_session(self):
        app = self.companion()
        pc = self.AdvertisingPC()
        first, go = threading.Event(), threading.Event()

        def standin(client, _source, **_kwargs):
            if client is not pc:
                return SimpleNamespace(run=lambda stop: stop.wait(10))

            def run(stop):
                pc.hello()
                first.set()
                go.wait(5)
                pc.hello()
                stop.wait(10)
            return SimpleNamespace(run=run)

        with patch.object(link, "StandIn", side_effect=standin):
            app._start_worker(pc)
            self.assertTrue(first.wait(3))
            pc.state["epoch"] = b"\x02" * proto.EPOCH_BYTES
            pc.state["advertise"] = 500
            go.set()
            self.assertTrue(self.wait_for(lambda: app.worker_stop.is_set()))
            app.worker.join(3)
            self.assertFalse(app.worker.is_alive())
            self.assertFalse(app._workers_alive())  # tick() will tear down and reconnect
        lines = []
        while not app.events.empty():
            lines.append(app.events.get_nowait()[1])
        self.assertIn("Phone restarted; reconnecting PC models", lines)

    def test_phone_restart_with_legacy_rejection_restarts_the_session(self):
        app = self.companion()
        pc = self.AdvertisingPC()
        first, go = threading.Event(), threading.Event()
        original_send = pc.send

        def send(method, target, body=b"", signed=True):
            if target == "/v1/advertise" and pc.advertisements >= 1:
                pc.advertisements += 1
                return 400, {"error": "request"}  # advertise() reports "not enabled" without raising
            return original_send(method, target, body, signed)

        pc.send = send

        def standin(client, _source, **_kwargs):
            if client is not pc:
                return SimpleNamespace(run=lambda stop: stop.wait(10))

            def run(stop):
                pc.hello()
                first.set()
                go.wait(5)
                pc.hello()
                stop.wait(10)
            return SimpleNamespace(run=run)

        with patch.object(link, "StandIn", side_effect=standin):
            app._start_worker(pc)
            self.assertTrue(first.wait(3))
            pc.state["epoch"] = b"\x02" * proto.EPOCH_BYTES
            go.set()
            self.assertTrue(self.wait_for(lambda: app.worker_stop.is_set()))
            app.worker.join(3)
            self.assertFalse(app.worker.is_alive())
        self.stop_everything(app)

    def test_real_pc_hello_retries_a_failed_restart_callback(self):
        from gpu_link_worker import PC as RealPC

        class Greeting(RealPC):
            def __init__(self):
                self.host, self.port, self.key, self.label = "127.0.0.1", 18767, b"K" * 32, "Test PC"
                self.epoch, self.request_limit = None, 1
                self.current = b"\x07" * proto.EPOCH_BYTES

            def send(self, method, target, body=b"", signed=True):
                return 200, json.loads(proto.hello_body(self.label, self.current))

        pc, calls = Greeting(), []
        pc.hello()

        def failing(epoch):
            calls.append(epoch)
            if len(calls) == 1:
                raise RuntimeError("callback failed")

        pc.on_new_epoch = failing
        pc.current = b"\x08" * proto.EPOCH_BYTES
        with self.assertRaises(RuntimeError):
            pc.hello()
        pc.hello()  # the unhandled restart is reported again rather than swallowed
        self.assertEqual(calls, [b"\x08" * proto.EPOCH_BYTES] * 2)

    def test_real_pc_hello_reports_epoch_changes_only(self):
        from gpu_link_worker import PC as RealPC

        class Greeting(RealPC):
            def __init__(self):
                self.host, self.port, self.key, self.label = "127.0.0.1", 18767, b"K" * 32, "Test PC"
                self.epoch, self.request_limit = None, 1
                self.current = b"\x07" * proto.EPOCH_BYTES

            def send(self, method, target, body=b"", signed=True):
                return 200, json.loads(proto.hello_body(self.label, self.current))

        pc, renewed = Greeting(), []
        pc.on_new_epoch = renewed.append
        pc.hello()
        self.assertEqual(renewed, [])  # first greeting is not a restart
        pc.epoch = None  # a transport error clears the live epoch...
        pc.hello()
        self.assertEqual(renewed, [])  # ...but the same phone is not a restart
        pc.current = b"\x08" * proto.EPOCH_BYTES
        pc.hello()
        self.assertEqual(renewed, [b"\x08" * proto.EPOCH_BYTES])


class R23ReplugWithLanesTests(unittest.TestCase):
    """Cable pull and backend restart through tick(), with the real worker and extra PC lanes."""

    class LanePhone(FakePC):
        host, port = "127.0.0.1", 18767
        advertisements = 0

        def send(self, method, target, body=b"", signed=True):
            if target == "/v1/advertise":
                R23ReplugWithLanesTests.LanePhone.advertisements += 1
                return 200, {"accepted": len(json.loads(body)["models"])}
            raise AssertionError(target)

    def test_replug_and_backend_restart_keep_lanes_consistent(self):
        R23ReplugWithLanesTests.LanePhone.advertisements = 0
        with tempfile.TemporaryDirectory() as directory:
            fake = FakeAdb()
            fake.state = "device"
            fake.assigned = list(range(18767, 18800))
            now = [100.0]
            app = app_fixture(directory, fake, now)
            app.args.extra_models = [dict(m) for m in R23WorkerLifecycleTests.MODELS[:2]]
            app._start_worker = lambda pc: link.Companion._start_worker(app, pc)
            app.keys.save_first_allow(bytes(range(32)))
            backend = [True]

            def idle(pc):
                if not backend[0]:
                    raise OSError("connection refused")
                return True

            def serve(client, _source, **_kwargs):
                return SimpleNamespace(run=lambda stop: stop.wait(10))

            started = time.monotonic()
            with patch.object(link, "PC", self.LanePhone), \
                    patch.object(link, "authenticated_idle", side_effect=idle), \
                    patch.object(link, "model_server_listening", return_value=True), \
                    patch.object(link, "model_server_preflight", return_value=True), \
                    patch.object(link, "StandIn", side_effect=serve):
                try:
                    app.tick()
                    finish_preflight(app)
                    self.assertTrue(app.online)
                    self.assertTrue(R23WorkerLifecycleTests.wait_for(lambda: len(app.lane_workers) == 2))
                    first_lanes = app.lane_workers
                    for _ in range(5):  # steady state: ticks must not tear the session down
                        now[0] += 1
                        app.tick()
                        self.assertTrue(app.online, app.lines[-1:])
                    self.assertEqual(app.lane_workers, first_lanes)
                    self.assertEqual(self.LanePhone.advertisements, 1)
                    app.extra_checked.add(R23WorkerLifecycleTests.MODELS[0]["id"])

                    # Cable pulled while the phone backend is dead as well.
                    fake.state = "offline"
                    fake.forwards.clear()
                    backend[0] = False
                    now[0] += 1
                    app.tick()
                    self.assertFalse(app.online)
                    self.assertEqual(app.lane_workers, ())
                    self.assertFalse(any(t.is_alive() for t in first_lanes))
                    self.assertEqual(app.extra_checked, set())
                    self.assertIn("Phone disconnected", app.lines[-1])

                    # Replugged, backend still down: keep retrying quietly.
                    fake.state = "device"
                    for _ in range(3):
                        now[0] = app.next_try
                        app.tick()
                        self.assertIn("Phone service unavailable", app.lines[-1])
                        self.assertFalse(app.online)

                    # Backend restarted: a fresh session advertises again and publishes fresh lanes.
                    backend[0] = True
                    now[0] = app.next_try
                    app.tick()
                    finish_preflight(app)
                    self.assertTrue(app.online)
                    self.assertTrue(R23WorkerLifecycleTests.wait_for(lambda: len(app.lane_workers) == 2))
                    self.assertTrue(set(app.lane_workers).isdisjoint(first_lanes))
                    self.assertTrue(app._workers_alive())
                    self.assertEqual(self.LanePhone.advertisements, 2)
                    for _ in range(3):
                        now[0] += 1
                        app.tick()
                        self.assertTrue(app.online)
                finally:
                    app.running = False
                    app._stop_worker()
            self.assertLess(time.monotonic() - started, 15)


if __name__ == "__main__":
    unittest.main()

"""Launcher guard wiring with in-memory children and no sockets/model runtime."""
import hashlib
import queue
import json
import os
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gpu_link_autosetup as setup
import gpu_link_health as health
import gpu_link_worker as worker
import opos_gpu_link as link

POPEN = subprocess.Popen

def process(argv, pid=65001):
    child = Mock(spec=POPEN)
    child.pid, child.args, child._child_created = pid, list(argv), True
    child.poll.return_value = None
    def stopped(*_args, **_kwargs):
        child.poll.return_value = 0
        return 0
    child.terminate.side_effect = stopped
    child.send_signal.side_effect = stopped
    child.kill.side_effect = stopped
    child.wait.side_effect = stopped
    return child


class RuntimeFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old = self.root / "large.gguf"
        self.small = self.root / "small.gguf"
        self.old.write_bytes(b"original")
        self.small.write_bytes(b"tiny")
        self.key = "test-credential-value-with-no-production-access"
        self.alias = setup.ALIAS
        self.rt = setup.Runtime()
        self.rt.key = self.key
        self.rt.args = SimpleNamespace(no_download=True, models_dir=self.root)
        self.argv = setup.server_command("fake-llama", self.old, 18090, "/expired/k", self.alias, "cpu")
        self.child = process(self.argv)
        self.server = setup.LaunchedServer(self.child, 18090, self.root / "server.log", self.alias)
        self.server.launch = dict(argv=tuple(self.argv), env={"SLOT": "preserved"},
                                  options={"cwd": str(self.root)}, model_path=self.old, size=8,
                                  log_path=self.server.log_path, port=18090, alias=self.alias,
                                  process=self.child, pid=self.child.pid, backend="cpu", ctx=8192, profile=None, device=None)
        self.rt.servers = [self.server]
        self.rt.launches = {18090: self.server.launch}
        self.rt.lanes = [dict(id=self.alias, label="Original", maker="Local", url=self.server.base_url + "/v1/chat/completions")]
        self.original = health.Model("Original", 8, self.old, available=True)
        self.candidate = health.Model("Small", 4, self.small,
                                      sha256=hashlib.sha256(b"tiny").hexdigest(), available=True)
        self.rt.models = {self.alias: self.original}
        self.rt.catalog_entries = {"Small": dict(file="small.gguf", label="Small", size=4,
                                                 sha256=self.candidate.sha256)}
        self.rt.fallback_plan = health.FallbackPlan([self.candidate], offline=True)
        self.job = dict(lease="lease-one", question="Same question", partial="")

    def terminal(self, code="garbled"):
        return SimpleNamespace(snapshot=lambda: (b"safe prefix", True, "stop", None, True),
                               error_code=code, close=Mock())

    def test_duplicate_terminal_snapshots_and_transport_resume_count_once(self):
        first = link.RuntimeSource(lambda: self.terminal(), self.rt, self.alias, self.job)
        first.snapshot()
        first.snapshot()
        resumed = link.RuntimeSource(lambda: self.terminal(), self.rt, self.alias, dict(self.job))
        resumed.snapshot()
        self.assertEqual(self.rt.fallback_plan.failure_count(self.alias, self.job["question"]), 1)

    def test_two_leases_same_question_offer_one_swap(self):
        with patch.object(self.rt, "_fallback") as fallback:
            self.rt.record_failure(self.alias, self.job, "garbled")
            self.rt.record_failure(self.alias, dict(self.job, lease="lease-two"), "stream_error")
            self.rt.fallback_threads[-1].join(1)
            fallback.assert_called_once_with(self.alias, self.job["question"], self.candidate)
        self.assertEqual(self.rt.fallback_plan.failure_count(self.alias, self.job["question"]), 2)

    def test_pending_replacement_keeps_lane_warming_without_counting(self):
        self.rt.pending.add(self.alias)
        build = Mock()
        source = link.RuntimeSource(build, self.rt, self.alias, self.job)
        self.assertTrue(source.warming)
        self.assertFalse(source.snapshot()[-1])
        build.assert_not_called()
        self.assertEqual(self.rt.fallback_plan.failure_count(self.alias, self.job["question"]), 0)

    def test_advertisement_acceptance_gates_new_extra_source(self):
        accepted = [False]
        build = Mock(return_value=self.terminal())
        source = link.RuntimeSource(build, self.rt, self.alias, self.job, lambda: accepted[0])
        source.snapshot()
        build.assert_not_called()
        accepted[0] = True
        source.snapshot()
        build.assert_called_once()

    def test_cancelled_source_does_not_count(self):
        source = link.RuntimeSource(lambda: self.terminal(), self.rt, self.alias, self.job)
        source.close()
        source.snapshot()
        self.assertEqual(self.rt.fallback_plan.failure_count(self.alias, self.job["question"]), 0)

    def test_server_and_constructor_failures_have_policy_reasons(self):
        with patch.object(self.rt, "record_failure") as record:
            source = link.RuntimeSource(lambda: self.terminal("server"), self.rt, self.alias, self.job)
            source.snapshot()
            self.assertEqual(record.call_args.args[-1], "stream_error")
            build = Mock(side_effect=OSError("fake start failure"))
            link.RuntimeSource(build, self.rt, self.alias, self.job).snapshot()
            self.assertEqual(record.call_args.args[-1], "model_start")

    def test_crash_is_counted_once_for_active_attempt(self):
        streaming = SimpleNamespace(snapshot=lambda: (b"", False, "stop", None, False), close=Mock())
        source = link.RuntimeSource(lambda: streaming, self.rt, self.alias, self.job)
        source.snapshot()
        self.rt.crashes[self.alias] = 1
        with patch.object(self.rt, "record_failure") as record:
            self.assertTrue(source.snapshot()[-1])
            source.snapshot()
            record.assert_called_once_with(self.alias, self.job, "crash")

    def test_secure_restart_recreates_key_append_log_and_preserves_spawn(self):
        self.server.log_path.write_bytes(b"earlier\n")
        seen = {}
        def spawn(argv, **options):
            key_path = Path(argv[argv.index("--api-key-file") + 1])
            seen.update(key_path=key_path, mode=key_path.stat().st_mode & 0o777,
                        key=key_path.read_text(), options=options, argv=list(argv))
            options["stdout"].write(b"restart\n")
            return process(argv, 65002)
        with patch.object(setup.subprocess, "Popen", side_effect=spawn), patch.object(setup, "wait_healthy", return_value=True):
            result = self.rt._restart_owned(self.argv)
        self.assertEqual(seen["mode"], 0o600)
        self.assertEqual(seen["key"], self.key + "\n")
        self.assertNotIn(self.key, " ".join(seen["argv"]))
        self.assertEqual(seen["options"]["env"], {"SLOT": "preserved"})
        self.assertEqual(seen["options"]["cwd"], str(self.root))
        self.assertFalse(seen["key_path"].exists())
        self.assertEqual(self.server.log_path.read_bytes(), b"earlier\nrestart\n")
        self.assertIs(self.rt.launches[18090]["process"], result)
        self.assertEqual(result.args, self.argv)

    def test_failed_restart_cleans_new_child_and_key(self):
        child = process(self.argv, 65002)
        paths = []
        def spawn(argv, **_options):
            paths.append(Path(argv[argv.index("--api-key-file") + 1]))
            return child
        with patch.object(setup.subprocess, "Popen", side_effect=spawn), patch.object(setup, "wait_healthy", return_value=False):
            with self.assertRaises(OSError):
                self.rt._restart_owned(self.argv)
        child.send_signal.assert_called_once()
        self.assertFalse(paths[0].exists())

    def test_shutdown_cancels_and_joins_before_child_and_key_cleanup(self):
        order = []
        self.rt.supervisor = SimpleNamespace(join=lambda: order.append(("join", self.rt.stopping.is_set(), self.rt.key)))
        self.server.stop = lambda: order.append(("stop", self.rt.stopping.is_set(), self.rt.key))
        self.rt.stop()
        self.assertEqual([item[0] for item in order], ["join", "stop"])
        self.assertTrue(all(item[1] and item[2] == self.key for item in order))
        self.assertIsNone(self.rt.key)

    def test_shutdown_refuses_tampered_process(self):
        foreign = process(self.argv, 65003)
        self.server.process = foreign
        self.rt.stop()
        foreign.send_signal.assert_not_called()
        foreign.terminate.assert_not_called()

    def test_shutdown_refuses_tampered_pid(self):
        self.child.pid = 41484
        self.rt.stop()
        self.child.send_signal.assert_not_called()
        self.child.terminate.assert_not_called()

    def test_accepted_advertisement_captures_sent_revision_before_concurrent_swap(self):
        models = [dict(id=self.alias, label="Original", maker="Local", gpu=None)]
        sent = []
        def send(_method, _target, body):
            sent.append(json.loads(body))
            with self.rt.state_lock:
                self.rt.lanes[0]["label"] = "Small (fallback for Original)"
                self.rt.revision += 1
            return 200, {"accepted": 1}
        enabled, revision = link.advertise_runtime_models(SimpleNamespace(send=send), models, self.rt)
        self.assertTrue(enabled)
        self.assertEqual(revision, 0)
        self.assertEqual(self.rt.revision, 1)
        self.assertEqual(sent[0]["models"][0]["label"], "Original")

    def test_rejected_advertisement_is_not_accepted(self):
        pc = SimpleNamespace(send=lambda *_args: (500, {"error": "request"}))
        with self.assertRaises(link.ToolError):
            link.advertise_runtime_models(pc, [], self.rt)

    def test_smaller_fallback_updates_same_slot_after_ready(self):
        self.rt.watchdog = Mock()
        child = process(self.argv, 65002)
        events = []
        self.rt.listen(events.append)
        with patch.object(setup.subprocess, "Popen", return_value=child), patch.object(setup, "wait_healthy", return_value=True), patch.object(health, "port_available", return_value=True):
            self.rt._fallback(self.alias, self.job["question"], self.candidate)
        self.assertEqual(self.rt.lane(self.alias)["label"], "Small (fallback for Original)")
        self.assertEqual(self.server.port, 18090)
        self.assertIs(self.server.process, child)
        self.assertEqual(self.rt.launches[18090]["model_path"], self.small)
        self.rt.watchdog.release.assert_called_once_with(self.server)
        self.rt.watchdog.adopt.assert_called_once()
        self.assertEqual(events[-1]["status"], "fallback")
        self.assertNotIn(self.key, repr(events))

    def test_offline_missing_candidate_never_downloads_or_launches(self):
        candidate = health.Model("Small", 4, sha256=self.candidate.sha256)
        with patch.object(setup, "ensure_model", wraps=setup.ensure_model) as ensure, patch.object(setup.subprocess, "Popen") as spawn:
            self.rt._fallback(self.alias, self.job["question"], candidate)
        self.assertFalse(ensure.call_args.args[-1])
        spawn.assert_not_called()

    def test_failed_replacement_is_terminal_without_new_source(self):
        self.rt.fallback_plan.record_failure(self.alias, "q", self.original, "garbled")
        self.rt.fallback_plan.record_failure(self.alias, "q", self.original, "garbled")
        with patch.object(setup, "wait_healthy", return_value=False), patch.object(setup.subprocess, "Popen", return_value=process(self.argv, 65002)), patch.object(health, "port_available", return_value=True):
            self.rt._fallback(self.alias, "q", self.candidate)
        build = Mock()
        source = link.RuntimeSource(build, self.rt, self.alias, self.job)
        self.assertTrue(source.snapshot()[-1])
        self.assertEqual(source.error_code, "fallback_failed")
        build.assert_not_called()

    def test_catalog_snapshot_only_marks_pinned_verified_local_files(self):
        row = dict(self.rt.catalog_entries["Small"], name="small.gguf")
        args = SimpleNamespace(models_dir=self.root, data_dir=self.root, no_download=True)
        with patch.object(setup, "profile_catalog", return_value=[row]), patch.object(setup, "scan_local_ggufs", return_value=[]), patch.object(setup, "model_dirs", return_value=[]), patch.object(setup, "watchdog_enabled", return_value=False):
            self.rt.start_guards(args, {})
        self.assertTrue(self.rt.fallback_plan.models[0].available)
        self.assertTrue(self.rt.fallback_plan.offline)

    def test_standard_catalog_path_handles_no_profile(self):
        args = SimpleNamespace(models_dir=self.root, data_dir=self.root, no_download=True)
        with patch.object(setup, "scan_local_ggufs", return_value=[]), patch.object(setup, "model_dirs", return_value=[]), patch.object(setup, "watchdog_enabled", return_value=False):
            self.rt.start_guards(args, {})
        self.assertGreater(len(self.rt.fallback_plan.catalog), 0)
        self.assertIsNone(self.rt.watchdog)

    def test_owned_child_exit_during_signal_is_clean(self):
        self.child.send_signal.side_effect = ProcessLookupError("already exited")
        self.server.stop(quiet=True)

    def test_shutdown_attempts_remaining_children_and_drops_key_after_error(self):
        failed = Mock(port=18091)
        failed.stop.side_effect = OSError("fake cleanup failure")
        self.rt.servers.append(failed)
        with self.assertRaises(OSError):
            self.rt.stop()
        self.child.send_signal.assert_called_once()
        self.assertIsNone(self.rt.key)


    def start_companion_worker(self, pc):
        app = link.Companion.__new__(link.Companion)
        app.running, app.events = True, queue.SimpleQueue()
        app.args = SimpleNamespace(model=self.alias, runtime=self.rt, extra_models=[])
        with patch.object(link, "StandIn"):
            app._start_worker(pc)
            app.worker.join(2)
        self.assertFalse(app.worker.is_alive())

    def test_startup_lane_label_is_published_before_fallback(self):
        pc = worker.PC("127.0.0.1:38641", bytes(range(32)))
        self.start_companion_worker(pc)
        self.assertNotIn("lead_label", self.rt.lanes[0])
        self.assertEqual(pc.lead_label_source(), "Original")
        self.rt.lanes[0]["lead_label"] = "Served model"
        self.assertEqual(pc.lead_label_source(), "Served model")
        self.rt.lanes[0]["lead_label"] = None
        self.assertEqual(pc.lead_label_source(), "Original")

    def test_failed_fallback_keeps_the_served_startup_label(self):
        pc = worker.PC("127.0.0.1:38641", bytes(range(32)))
        self.start_companion_worker(pc)
        replacement = process(self.argv, 65002)
        def not_ready(*_args, **_kwargs):
            self.assertEqual(pc.lead_label_source(), "Original")
            return False
        with patch.object(setup.subprocess, "Popen", return_value=replacement), \
                patch.object(setup, "wait_healthy", side_effect=not_ready), \
                patch.object(health, "port_available", return_value=True):
            self.rt._fallback(self.alias, self.job["question"], self.candidate)
        self.assertEqual(pc.lead_label_source(), "Original")


    def test_existing_server_never_adopts_or_scans(self):
        self.rt.existing = True
        with patch.object(setup, "Watchdog") as watchdog, patch.object(setup, "scan_local_ggufs") as scan:
            self.rt.start_guards(None, {})
        watchdog.assert_not_called()
        scan.assert_not_called()

    def test_protected_ports_never_launch(self):
        with patch.object(setup.subprocess, "Popen") as spawn:
            for port in health.PROTECTED_PORTS:
                with self.subTest(port=port), self.assertRaises(ValueError):
                    setup.launch_llama_server("fake", self.old, port, {}, self.root, "cpu", "/unused/k")
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()

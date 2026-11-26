"""Independent recovery lifecycle regressions; no real sockets or subprocesses."""
import os
import threading
import unittest
from unittest.mock import Mock, patch

import gpu_link_autosetup as setup
import gpu_link_health as health
import opos_gpu_link as link
import test_gpu_link_runtime_integration as integration


class RecoveryLifecycleTests(unittest.TestCase):
    setUp = integration.RuntimeFixture.setUp
    terminal = integration.RuntimeFixture.terminal

    def test_terminal_sources_drive_one_real_policy_swap_then_stop_on_candidate_failure(self):
        replacement = integration.process(self.argv, 65002)
        with patch.object(setup.subprocess, "Popen", return_value=replacement) as spawn, \
                patch.object(setup, "wait_healthy", return_value=True), \
                patch.object(health, "port_available", return_value=True):
            first = link.RuntimeSource(lambda: self.terminal(), self.rt, self.alias, self.job)
            first.snapshot()
            second_job = dict(self.job, lease="second-terminal-attempt")
            second = link.RuntimeSource(lambda: self.terminal(), self.rt, self.alias, second_job)
            second.snapshot()
            fallback = self.rt.fallback_threads[-1]
            fallback.join(3)
            self.assertFalse(fallback.is_alive())
            self.assertEqual(self.rt.lane(self.alias)["label"], "Small (fallback for Original)")
            self.assertIs(self.server.process, replacement)
            self.assertNotIn(self.alias, self.rt.pending)
            self.assertEqual(self.rt.fallback_plan.failure_count(self.alias, self.job["question"]), 2)

            failed_candidate = link.RuntimeSource(lambda: self.terminal("server"), self.rt, self.alias,
                                                 dict(self.job, lease="candidate-attempt"))
            self.assertTrue(failed_candidate.snapshot()[-1])
            self.assertEqual(failed_candidate.error_code, "fallback_failed")
            another_factory = Mock()
            later = link.RuntimeSource(another_factory, self.rt, self.alias,
                                       dict(self.job, lease="later-attempt", question="Another question"))
            self.assertTrue(later.snapshot()[-1])
            self.assertEqual(later.error_code, "fallback_failed")
            another_factory.assert_not_called()
            spawn.assert_called_once()

    def test_supervisor_starts_by_default_ticks_owned_watchdog_and_joins(self):
        ticked = threading.Event()
        watchdog = Mock()
        watchdog.tick.side_effect = lambda: ticked.set()
        args = type("Args", (), dict(models_dir=self.root, data_dir=self.root, no_download=True))()
        with patch.dict(os.environ, {health.WATCHDOG_ENV: "1"}), \
                patch.object(setup, "profile_catalog", return_value=[]), \
                patch.object(setup, "scan_local_ggufs", return_value=[]), \
                patch.object(setup, "model_dirs", return_value=[]), \
                patch.object(setup, "Watchdog", return_value=watchdog) as constructor:
            try:
                self.rt.start_guards(args, {})
                self.assertTrue(ticked.wait(3), "supervisor never ticked")
                self.assertEqual(constructor.call_args.kwargs["allowed_ports"], frozenset({18090}))
                self.assertIs(constructor.call_args.args[0], self.rt)
            finally:
                self.rt.stop_supervision()
        self.assertFalse(self.rt.supervisor.is_alive())
        self.assertTrue(self.rt.stopping.is_set())

    def test_disabling_watchdog_retains_fallback_plan_without_starting_supervision(self):
        args = type("Args", (), dict(models_dir=self.root, data_dir=self.root, no_download=True))()
        with patch.dict(os.environ, {health.WATCHDOG_ENV: "0"}), \
                patch.object(setup, "profile_catalog", return_value=[]), \
                patch.object(setup, "scan_local_ggufs", return_value=[]), \
                patch.object(setup, "model_dirs", return_value=[]), \
                patch.object(setup, "Watchdog") as constructor:
            self.rt.start_guards(args, {})
        constructor.assert_not_called()
        self.assertIsNone(self.rt.supervisor)
        self.assertIsNotNone(self.rt.fallback_plan)

    def test_failed_candidate_cleanup_still_reports_failure_and_shutdown_retries_own_child(self):
        self.rt.fallback_plan.record_failure(self.alias, "q", self.original, "garbled")
        self.rt.fallback_plan.record_failure(self.alias, "q", self.original, "garbled")
        replacement = integration.process(self.argv, 65002)
        replacement.send_signal.side_effect = OSError("fake cleanup failure")
        replacement.terminate.side_effect = OSError("fake cleanup failure")
        events = []
        self.rt.listen(events.append)
        with patch.object(setup.subprocess, "Popen", return_value=replacement), \
                patch.object(setup, "wait_healthy", return_value=False), \
                patch.object(health, "port_available", return_value=True):
            self.rt._fallback(self.alias, "q", self.candidate)
        self.assertEqual(self.rt.fallback_plan.status(self.alias), "fallback_failed")
        self.assertEqual(events[-1]["status"], "fallback_failed")
        self.assertTrue(any(event["status"] == "cleanup_failed" for event in events))
        self.assertNotIn(self.alias, self.rt.pending)
        self.assertEqual(len(self.rt.failed_children), 1)
        replacement.send_signal.side_effect = lambda *_args: setattr(replacement.poll, "return_value", 0)
        replacement.terminate.side_effect = lambda: setattr(replacement.poll, "return_value", 0)
        self.rt.stop()
        self.assertEqual(self.rt.failed_children, [])
        self.assertIsNone(self.rt.key)


if __name__ == "__main__":
    unittest.main()

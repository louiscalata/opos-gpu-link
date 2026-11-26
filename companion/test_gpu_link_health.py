# SPDX-License-Identifier: Apache-2.0
"""Watchdog policy tests using only injected clocks and fake child processes."""
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gpu_link_health as health


PORT = 38441
COMMAND = ["fake", "--host", "127.0.0.1", "--port", str(PORT)]


class Clock:
    def __init__(self):
        self.now = 100.0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


class FakeProcess:
    def __init__(self, pid, command):
        self.pid = pid
        self.args = list(command)
        self.returncode = None
        self.terminated = 0
        self.killed = 0
        self.waits = []
        self.hang_on_terminate = False

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated += 1
        if not self.hang_on_terminate:
            self.returncode = -15

    def kill(self):
        self.killed += 1
        self.returncode = -9

    def wait(self, timeout=None):
        self.waits.append(timeout)
        if self.returncode is None:
            raise subprocess.TimeoutExpired(self.args, timeout)
        return self.returncode


class FakeFactory:
    def __init__(self):
        self.calls = []
        self.processes = []
        self.fail = False

    def __call__(self, command, **options):
        self.calls.append((list(command), dict(options)))
        if self.fail:
            raise OSError("simulated process failure")
        process = FakeProcess(200000 + len(self.processes), command)
        self.processes.append(process)
        return process


class WatchdogTests(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.factory = FakeFactory()
        self.health_calls = []
        self.free_calls = []
        self.events = []
        self.healthy = True
        self.available = True
        self.watchdog = health.Watchdog(process_factory=self.factory, clock=self.clock,
                                       health=self.probe, free=self.free, notify=self.events.append,
                                       startup_grace=0, enabled=True)

    def probe(self, port):
        self.health_calls.append(port)
        return self.healthy

    def free(self, port):
        self.free_calls.append(port)
        return self.available

    def spawn(self, **options):
        return self.watchdog.spawn(COMMAND, PORT, **options)

    def restart_crash(self, server, delay=1):
        server.process.returncode = 1
        self.assertEqual(self.watchdog.tick()[0]["status"], "restart_pending")
        self.clock.advance(delay)
        return self.watchdog.tick()

    def test_crash_restarts_same_command_environment_and_port(self):
        server = self.spawn(env={"TEST_SETTING": "test-value"}, cwd="/test-checkout")
        original = server.process
        self.assertEqual(self.restart_crash(server)[-1]["status"], "restarted")
        self.assertIsNot(server.process, original)
        self.assertTrue(self.watchdog.owns(server))
        self.assertEqual(self.factory.calls[0], self.factory.calls[1])
        self.assertEqual(server.port, PORT)
        self.assertEqual(original.terminated, 0)
        self.assertEqual(original.killed, 0)
        self.assertEqual(self.health_calls, [])

    def test_two_health_misses_do_not_restart(self):
        self.spawn()
        self.healthy = False
        self.assertEqual(self.watchdog.tick(), [])
        self.assertEqual(self.watchdog.tick(), [])
        self.assertEqual(len(self.factory.calls), 1)

    def test_third_health_miss_schedules_restart_with_backoff(self):
        server = self.spawn()
        original = server.process
        self.healthy = False
        for _ in range(2):
            self.watchdog.tick()
        self.assertEqual(self.watchdog.tick()[0]["status"], "restart_pending")
        self.assertEqual(original.terminated, 0)
        self.clock.advance(0.9)
        self.assertEqual(self.watchdog.tick(), [])
        self.clock.advance(0.1)
        self.assertEqual(self.watchdog.tick()[-1]["status"], "restarted")
        self.assertEqual(original.terminated, 1)
        self.assertEqual(original.killed, 0)

    def test_successful_health_response_resets_miss_counter(self):
        server = self.spawn()
        self.healthy = False
        self.watchdog.tick()
        self.watchdog.tick()
        self.assertEqual(server.misses, 2)
        self.healthy = True
        self.watchdog.tick()
        self.assertEqual(server.misses, 0)
        self.healthy = False
        self.watchdog.tick()
        self.watchdog.tick()
        self.assertIsNone(server.next_restart)
        self.assertEqual(self.watchdog.tick()[0]["status"], "restart_pending")

    def test_startup_grace_defers_health_checks_but_not_crashes(self):
        self.watchdog.startup_grace = 10
        server = self.spawn()
        self.healthy = False
        self.watchdog.tick()
        self.clock.advance(9)
        self.watchdog.tick()
        self.assertEqual(self.health_calls, [])
        self.clock.advance(1)
        self.watchdog.tick()
        self.assertEqual(self.health_calls, [PORT])
        self.restart_crash(server)
        self.assertEqual(server.ready_after, self.clock() + 10)
        self.watchdog.tick()
        self.assertEqual(self.health_calls, [PORT])

    def test_crash_during_initial_grace_is_detected(self):
        self.watchdog.startup_grace = 60
        server = self.spawn()
        self.assertEqual(self.restart_crash(server)[-1]["status"], "restarted")

    def test_owned_identity_is_required_even_if_foreign_pid_matches(self):
        server = self.spawn()
        original = server.process
        foreign = FakeProcess(original.pid, COMMAND)
        server.process = foreign
        self.assertFalse(self.watchdog.owns(server))
        with self.assertRaisesRegex(ValueError, "do not own"):
            self.watchdog.stop(server)
        self.assertEqual(self.watchdog.tick()[0]["status"], "ownership_refused")
        self.assertEqual(foreign.terminated + foreign.killed, 0)
        self.assertEqual(original.terminated + original.killed, 0)
        self.assertEqual(len(self.factory.calls), 1)

    def test_changed_process_pid_is_refused(self):
        server = self.spawn()
        server.process.pid += 100
        self.assertFalse(self.watchdog.owns(server))
        self.assertEqual(self.watchdog.tick()[0]["status"], "ownership_refused")
        self.assertEqual(server.process.terminated + server.process.killed, 0)

    def test_untracked_server_handle_cannot_be_stopped(self):
        foreign = FakeProcess(300000, COMMAND)
        server = health.WatchedServer(foreign, PORT, tuple(COMMAND), pid=foreign.pid)
        with self.assertRaisesRegex(ValueError, "do not own"):
            self.watchdog.stop(server)
        self.assertEqual(foreign.terminated + foreign.killed, 0)

    def test_runtime_rejects_pid_and_fake_process_adoption(self):
        for process in (12345, FakeProcess(300001, COMMAND)):
            runtime = SimpleNamespace(servers=[SimpleNamespace(process=process, port=PORT)])
            with self.assertRaisesRegex(ValueError, "child Popen"):
                health.Watchdog(runtime, process_factory=self.factory, clock=self.clock,
                                health=self.probe, free=self.free, enabled=True,
                                spawn_options={PORT: {}})
        self.assertEqual(self.factory.calls, [])

    def test_protected_and_out_of_range_ports_refused_before_probe(self):
        for port in (1234, 1235, 1236, 1237, 8765, 8767, 11434, 41484, 56795,
                     56740, 24001, 38399, 38500, 0, True):
            command = ["fake", "--host", "127.0.0.1", "--port", str(port)]
            with self.subTest(port=port), self.assertRaises(ValueError):
                self.watchdog.spawn(command, port)
        self.assertEqual(self.free_calls, [])
        self.assertEqual(self.factory.calls, [])

    def test_protected_helper_checks_never_open_socket(self):
        with patch.object(health.socket, "socket", side_effect=AssertionError("socket opened")), \
                patch.object(health.http.client, "HTTPConnection", side_effect=AssertionError("connected")):
            self.assertFalse(health.port_available(1235))
            self.assertFalse(health.server_healthy(1235))

    def test_protected_pid_from_factory_is_refused_without_signal(self):
        process = FakeProcess(41484, COMMAND)
        self.watchdog.process_factory = lambda *args, **kwargs: process
        with self.assertRaisesRegex(ValueError, "Protected"):
            self.spawn()
        self.assertEqual(self.watchdog.servers, [])
        self.assertEqual(process.terminated + process.killed, 0)

    def test_occupied_port_prevents_initial_spawn(self):
        self.available = False
        with self.assertRaisesRegex(ValueError, "already listening"):
            self.spawn()
        self.assertEqual(self.factory.calls, [])

    def test_occupied_port_after_crash_is_not_reused(self):
        server = self.spawn()
        self.available = False
        self.assertEqual(self.restart_crash(server)[-1]["status"], "port_busy")
        self.assertTrue(server.gave_up)
        self.assertEqual(len(self.factory.calls), 1)
        self.assertEqual(server.process.terminated + server.process.killed, 0)

    def test_duplicate_tracked_port_prevents_spawn(self):
        self.spawn()
        with self.assertRaisesRegex(ValueError, "already listening"):
            self.spawn()
        self.assertEqual(len(self.factory.calls), 1)

    def test_backoff_is_one_two_four_seconds(self):
        server = self.spawn()
        for delay in (1, 2, 4):
            server.process.returncode = 1
            self.watchdog.tick()
            self.assertEqual(server.next_restart, self.clock() + delay)
            self.clock.advance(delay - 0.1)
            self.assertEqual(self.watchdog.tick(), [])
            self.clock.advance(0.1)
            self.assertEqual(self.watchdog.tick()[-1]["status"], "restarted")
        self.assertEqual(len(self.factory.calls), 4)

    def test_three_restarts_per_ten_minutes_then_give_up(self):
        server = self.spawn()
        for delay in (1, 2, 4):
            self.restart_crash(server, delay)
        events = self.restart_crash(server, 8)
        self.assertEqual(events[-1]["status"], "gave_up")
        self.assertTrue(server.gave_up)
        self.assertEqual(len(self.factory.calls), 4)
        self.clock.advance(1000)
        self.assertEqual(self.watchdog.tick(), [])
        self.assertEqual(len(self.factory.calls), 4)

    def test_expired_attempts_allow_later_restart(self):
        server = self.spawn()
        for delay in (1, 2, 4):
            self.restart_crash(server, delay)
        self.clock.advance(601)
        self.assertEqual(self.restart_crash(server, 1)[-1]["status"], "restarted")
        self.assertEqual(len(server.attempts), 1)
        self.assertEqual(len(self.factory.calls), 5)

    def test_unsuccessful_spawn_attempts_count_toward_storm_limit(self):
        server = self.spawn()
        server.process.returncode = 1
        self.factory.fail = True
        self.watchdog.tick()
        for delay in (1, 2, 4):
            self.clock.advance(delay)
            self.assertEqual(self.watchdog.tick()[-1]["status"], "restart_failed")
        self.clock.advance(8)
        self.assertEqual(self.watchdog.tick()[-1]["status"], "gave_up")
        self.assertEqual(len(self.factory.calls), 4)
        self.assertEqual(len(server.attempts), 3)

    def test_disabled_watchdog_does_not_probe_or_restart(self):
        server = self.spawn()
        self.watchdog.enabled = False
        server.process.returncode = 1
        self.assertEqual(self.watchdog.tick(), [])
        self.assertEqual(self.health_calls, [])
        self.assertEqual(len(self.factory.calls), 1)

    def test_environment_switch_defaults_on_and_zero_disables(self):
        self.assertTrue(health.watchdog_enabled({}))
        self.assertTrue(health.watchdog_enabled({health.WATCHDOG_ENV: "1"}))
        self.assertFalse(health.watchdog_enabled({health.WATCHDOG_ENV: "0"}))
        with patch.dict(health.os.environ, {health.WATCHDOG_ENV: "0"}):
            watchdog = health.Watchdog(process_factory=self.factory, clock=self.clock,
                                      health=self.probe, free=self.free)
        self.assertFalse(watchdog.enabled)

    def test_close_stops_only_owned_process_and_disables_supervision(self):
        server = self.spawn()
        process = server.process
        self.watchdog.close()
        self.assertFalse(self.watchdog.enabled)
        self.assertEqual(process.terminated, 1)
        self.assertEqual(process.killed, 0)
        self.assertEqual(self.watchdog.tick(), [])

    def test_close_refuses_foreign_first_slot_but_still_stops_owned_second(self):
        first = self.spawn()
        original = first.process
        foreign = FakeProcess(original.pid, COMMAND)
        first.process = foreign
        second_port = PORT + 1
        command = ["fake", "--host", "127.0.0.1", "--port", str(second_port)]
        second = self.watchdog.spawn(command, second_port)
        with self.assertRaisesRegex(ValueError, "Foreign process refused"):
            self.watchdog.close()
        self.assertFalse(self.watchdog.enabled)
        self.assertEqual(foreign.terminated + foreign.killed, 0)
        self.assertEqual(original.terminated + original.killed, 0)
        self.assertEqual(second.process.terminated, 1)
        self.assertEqual(second.process.killed, 0)
        self.assertEqual(self.events[-1]["status"], "ownership_refused")

    def test_close_reports_stop_errors_after_stopping_remaining_owned_slots(self):
        for error in (OSError("simulated stop failure"),
                      subprocess.TimeoutExpired(COMMAND, 3)):
            with self.subTest(error=type(error).__name__):
                factory = FakeFactory()
                watchdog = health.Watchdog(process_factory=factory, clock=self.clock,
                                           health=self.probe, free=self.free, enabled=True)
                first = watchdog.spawn(COMMAND, PORT)
                second_port = PORT + 1
                command = ["fake", "--host", "127.0.0.1", "--port", str(second_port)]
                second = watchdog.spawn(command, second_port)
                with patch.object(first.process, "terminate", side_effect=error):
                    with self.assertRaises(type(error)) as raised:
                        watchdog.close()
                self.assertIs(raised.exception, error)
                self.assertFalse(watchdog.enabled)
                self.assertEqual(second.process.terminated, 1)
                self.assertEqual(second.process.killed, 0)

    def test_terminate_process_exit_race_is_treated_as_exited(self):
        server = self.spawn()
        foreign = FakeProcess(300000, COMMAND)

        def exited_before_signal():
            server.process.returncode = 0
            raise ProcessLookupError("child already exited")

        with patch.object(server.process, "terminate", side_effect=exited_before_signal) as terminate:
            self.watchdog.stop(server)
        terminate.assert_called_once_with()
        self.assertEqual(server.process.returncode, 0)
        self.assertEqual(server.process.killed, 0)
        self.assertEqual(server.process.waits, [])
        self.assertEqual(foreign.terminated + foreign.killed, 0)

    def test_tampered_restart_command_cannot_replay_on_protected_port(self):
        server = self.spawn()
        server.command = ("fake", "--host", "127.0.0.1", "--port", "1235")
        self.assertEqual(self.restart_crash(server)[-1]["status"], "restart_failed")
        self.assertEqual(len(self.factory.calls), 1)
        self.assertEqual(self.free_calls, [PORT, PORT])
        self.assertEqual(self.health_calls, [])

    def test_terminate_timeout_kills_only_our_child(self):
        server = self.spawn()
        server.process.hang_on_terminate = True
        self.watchdog.stop(server)
        self.assertEqual(server.process.terminated, 1)
        self.assertEqual(server.process.killed, 1)
        self.assertEqual(server.process.waits, [3, 3])

    def test_bad_ui_callback_cannot_prevent_recovery(self):
        def bad_callback(event):
            raise RuntimeError("UI unavailable")

        self.watchdog.notify = bad_callback
        server = self.spawn()
        self.assertEqual(self.restart_crash(server)[-1]["status"], "restarted")
        self.assertTrue(self.watchdog.owns(server))

    def test_health_exception_counts_as_miss(self):
        def failed_probe(port):
            raise OSError("simulated health failure")

        self.watchdog.health = failed_probe
        server = self.spawn()
        for _ in range(2):
            self.watchdog.tick()
        self.assertEqual(self.watchdog.tick()[0]["status"], "restart_pending")
        self.assertEqual(server.misses, 3)

    def test_callback_events_omit_command_environment_and_server_output(self):
        server = self.spawn(env={"PRIVATE_SETTING": "redacted-test-marker"})
        self.restart_crash(server)
        self.assertTrue(self.events)
        for event in self.events:
            self.assertEqual(set(event), {"port", "status", "restarts"})
            self.assertNotIn("redacted-test-marker", repr(event))

    def test_unsafe_or_ambiguous_commands_refused_without_spawn(self):
        bad_commands = [
            ["fake", "--host", "0.0.0.0", "--port", str(PORT)],
            ["fake", "--host", "127.0.0.1", "--port", "38442"],
            COMMAND + ["--host", "0.0.0.0"],
            COMMAND + ["--port=38442"],
            COMMAND + ["-p", "1235"],
            COMMAND + ["--listen", "0.0.0.0"],
            "fake --host 127.0.0.1 --port 38441",
        ]
        for command in bad_commands:
            with self.subTest(command=command), self.assertRaises(ValueError):
                self.watchdog.spawn(command, PORT)
        self.assertEqual(self.factory.calls, [])
        self.assertEqual(self.free_calls, [])

    def test_shell_and_preexec_options_refused_without_spawn(self):
        for options in ({"shell": True}, {"preexec_fn": lambda: None}):
            with self.subTest(options=options), self.assertRaisesRegex(ValueError, "Unsafe"):
                self.spawn(**options)
        self.assertEqual(self.factory.calls, [])


if __name__ == "__main__":
    unittest.main()

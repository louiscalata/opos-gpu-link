# SPDX-License-Identifier: Apache-2.0
"""Launcher port expansion and replacement ownership, with no real children/sockets."""
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gpu_link_health as health
from test_gpu_link_health import Clock, FakeFactory, FakeProcess


PORT = 18090


class FakeChild(FakeProcess, subprocess.Popen):
    def __init__(self, pid, command):
        FakeProcess.__init__(self, pid, command)
        self._child_created = True

    def __del__(self):
        pass


def target(port=PORT, pid=300001):
    command = ['fake', '--host', '127.0.0.1', '--port', str(port),
               '--api-key-file', '/deleted/private-file']
    return SimpleNamespace(port=port, process=FakeChild(pid, command))


class RuntimeWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.target = target()
        self.runtime = SimpleNamespace(servers=[self.target], existing=False)
        self.clock, self.factory = Clock(), FakeFactory()
        self.probes, self.binds = [], []

    def watchdog(self, **overrides):
        options = dict(process_factory=self.factory, clock=self.clock,
                       health=lambda port: self.probes.append(port) or True,
                       free=lambda port: self.binds.append(port) or True,
                       startup_grace=0, enabled=True,
                       spawn_options={PORT: {'env': {'LANE_SETTING': 'test'}, 'cwd': '/checkout'}},
                       allowed_ports=frozenset({PORT}))
        options.update(overrides)
        return health.Watchdog(self.runtime, **options)

    def test_runtime_adoption_requires_explicit_port_expansion(self):
        with self.assertRaises(ValueError):
            self.watchdog(allowed_ports=None)
        self.assertEqual(self.probes + self.binds, [])
        self.assertEqual(self.factory.calls, [])

    def test_owned_launcher_port_restarts_on_same_port_with_captured_options(self):
        watchdog = self.watchdog()
        watched = watchdog.servers[0]
        original = watched.process
        original.returncode = 1
        self.assertEqual(watchdog.tick()[0]['status'], 'restart_pending')
        self.clock.advance(1)
        self.assertEqual(watchdog.tick()[-1]['status'], 'restarted')
        self.assertEqual(watched.port, PORT)
        self.assertEqual(self.factory.calls, [(original.args,
                         {'env': {'LANE_SETTING': 'test'}, 'cwd': '/checkout'})])
        self.assertIs(self.target.process, watched.process)
        self.assertTrue(watchdog.owns(watched))
        self.assertEqual(self.probes, [])
        self.assertEqual(self.binds, [PORT])
        self.assertEqual(original.terminated + original.killed, 0)

    def test_expansion_does_not_allow_new_production_port_spawn(self):
        watchdog = self.watchdog()
        with self.assertRaisesRegex(ValueError, 'restricted to D ports'):
            watchdog.spawn(self.target.process.args, PORT)
        self.assertEqual(self.binds, [])
        self.assertEqual(self.factory.calls, [])

    def test_expansion_requires_runtime_and_existing_owned_slot(self):
        for runtime, ports in ((None, {PORT}), (self.runtime, {PORT + 1})):
            with self.subTest(ports=ports), self.assertRaisesRegex(ValueError, 'owned runtime slots'):
                health.Watchdog(runtime, allowed_ports=ports)
        self.assertEqual(self.factory.calls, [])

    def test_protected_invalid_and_boolean_port_expansion_refused(self):
        for port in (*health.PROTECTED_PORTS, 0, 65536, True, '18090'):
            with self.subTest(port=port), self.assertRaisesRegex(ValueError, 'Protected or invalid'):
                self.watchdog(allowed_ports={port})
        self.assertEqual(self.probes + self.binds, [])

    def test_discovered_runtime_is_never_adopted_even_on_d_port(self):
        self.runtime.existing = True
        with self.assertRaisesRegex(ValueError, 'owned runtime slots'):
            self.watchdog()
        foreign = target(38401)
        runtime = SimpleNamespace(servers=[foreign], existing=True)
        with self.assertRaisesRegex(ValueError, 'Existing or discovered'):
            health.Watchdog(runtime, process_factory=self.factory, enabled=True,
                            spawn_options={38401: {}})
        self.assertEqual(foreign.process.terminated + foreign.process.killed, 0)

    def test_replacement_releases_then_adopts_only_the_same_authorized_slot(self):
        watchdog = self.watchdog()
        original = self.target.process
        released = watchdog.release(self.target)
        self.assertEqual(watchdog.servers, [])
        self.assertFalse(watchdog.owns(released))
        self.assertEqual(original.terminated + original.killed, 0)
        replacement = target(pid=300002)
        self.runtime.servers[:] = [replacement]
        watched = watchdog.adopt(replacement, {'env': {'REPLACEMENT': 'test'}})
        self.assertTrue(watchdog.owns(watched))
        self.assertEqual(watched.port, PORT)
        self.assertEqual(watchdog.tick(), [])
        self.assertEqual(self.probes, [PORT])
        outside = target(PORT + 1, pid=300003)
        self.runtime.servers.append(outside)
        with self.assertRaises(ValueError):
            watchdog.adopt(outside, {})
        self.assertEqual(outside.process.terminated + outside.process.killed, 0)

    def test_adopt_refuses_foreign_or_nonchild_replacement(self):
        watchdog = self.watchdog()
        foreign = target(pid=300002)
        with self.assertRaisesRegex(ValueError, 'owned runtime slot'):
            watchdog.adopt(foreign, {})
        watchdog.release(self.target)
        foreign.process = FakeProcess(300003, foreign.process.args)
        self.runtime.servers[:] = [foreign]
        with self.assertRaisesRegex(ValueError, 'child Popen'):
            watchdog.adopt(foreign, {})

    def test_release_refuses_tampered_target_without_signal(self):
        watchdog = self.watchdog()
        original = self.target.process
        self.target.process = FakeProcess(original.pid, original.args)
        with self.assertRaisesRegex(ValueError, 'do not own'):
            watchdog.release(self.target)
        self.assertEqual(original.terminated + original.killed, 0)
        self.assertEqual(self.target.process.terminated + self.target.process.killed, 0)

    def test_default_health_and_bind_checks_use_the_explicit_runtime_port_set(self):
        watchdog = self.watchdog(health=health.server_healthy, free=health.port_available)
        with patch.object(health, 'server_healthy', return_value=True) as probe, \
                patch.object(health, 'port_available', return_value=True) as free:
            watchdog.tick()
            probe.assert_called_once_with(PORT, allowed_ports=watchdog._allowed_ports)
            self.target.process.returncode = 1
            watchdog.tick()
            self.clock.advance(1)
            watchdog.tick()
            free.assert_called_once_with(PORT, allowed_ports=watchdog._allowed_ports)


class ScopedPortHelpersTests(unittest.TestCase):
    def test_default_helpers_and_preflight_still_refuse_production_ports(self):
        with patch.object(health.socket, 'socket', side_effect=AssertionError('opened socket')), \
                patch.object(health.http.client, 'HTTPConnection', side_effect=AssertionError('connected')):
            self.assertFalse(health.safe_port(PORT))
            self.assertFalse(health.port_available(PORT))
            self.assertFalse(health.server_healthy(PORT))
            with self.assertRaises(ValueError):
                with health._http_deadline(PORT, 1):
                    self.fail('production port accepted without ownership')
            with self.assertRaises(ValueError):
                health.Preflight([], None, '.', port=PORT)

    def test_protected_ports_remain_refused_despite_explicit_set(self):
        for port in health.PROTECTED_PORTS:
            with self.subTest(port=port), \
                    patch.object(health.socket, 'socket', side_effect=AssertionError('opened socket')), \
                    patch.object(health.http.client, 'HTTPConnection', side_effect=AssertionError('connected')):
                self.assertFalse(health.port_available(port, allowed_ports=frozenset({port})))
                self.assertFalse(health.server_healthy(port, allowed_ports=frozenset({port})))

    def test_explicit_bind_scope_is_exact_and_never_connects(self):
        with patch.object(health.socket, 'has_ipv6', False), \
                patch.object(health.socket, 'socket') as socket_factory:
            self.assertTrue(health.port_available(PORT, allowed_ports=frozenset({PORT})))
            socket_factory.return_value.__enter__.return_value.bind.assert_called_once_with(('127.0.0.1', PORT))
            self.assertFalse(health.port_available(PORT + 1, allowed_ports=frozenset({PORT})))
            self.assertEqual(socket_factory.call_count, 1)


if __name__ == '__main__':
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Preflight policy with files, fake processes, fake counters and fake HTTP only."""
import errno
import hashlib
import socket
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from gpu_link_health import (Model, Preflight, headroom, memory_headroom,
                             preflight_garble_reason, preflight_port_free,
                             _http_deadline, warmup_text, server_healthy)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'model.gguf'
        self.path.write_bytes(b'fake model weights')
        self.model = Model('Qwen small', self.path.stat().st_size, self.path,
                           sha256=hashlib.sha256(self.path.read_bytes()).hexdigest(), available=True)
        self.servers = []
        self.stopped = []
        self.key_files = []
        self.calls = []

    def launcher(self, model, port, key_file):
        self.assertTrue(key_file.is_file())
        self.assertEqual(key_file.stat().st_mode & 0o777, 0o600)
        self.key_files.append(key_file)
        server = SimpleNamespace(port=port, alias='fake', process=SimpleNamespace(poll=lambda: None),
                                 stop=lambda quiet=True: self.stopped.append(port))
        self.servers.append(server)
        return server

    def run_check(self, models=None, **kwargs):
        options = dict(launcher=self.launcher, health=lambda s, t: True,
                       warmup=lambda s, k, t: 'A GPU renders frames using parallel calculations.',
                       memory=lambda: headroom(100, 50, 'fake'),
                       disk=lambda p: SimpleNamespace(free=1024 ** 3), free=lambda p: True)
        options.update(kwargs)
        return Preflight([self.model] if models is None else models, None, self.root / 'logs', **options).run()

    def test_success_records_checks_cleans_owned_server_and_key(self):
        result = self.run_check()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['models'][0]['warmup'], 'PASS')
        self.assertEqual(self.stopped, [38400])
        self.assertTrue(all(not path.exists() for path in self.key_files))
        self.assertNotIn('Bearer', json.dumps(result))
        self.assertEqual(result['downloads'], 'disabled')

    def test_missing_file_never_launches(self):
        self.path.unlink()
        result = self.run_check()
        self.assertEqual(result['models'][0]['file'], 'missing')
        self.assertEqual(result['exit_code'], 1)
        self.assertFalse(self.servers)

    def test_size_mismatch_never_launches(self):
        self.path.write_bytes(b'short')
        self.assertEqual(self.run_check()['models'][0]['file'], 'size_mismatch')
        self.assertFalse(self.servers)

    def test_hash_mismatch_never_launches(self):
        self.path.write_bytes(b'x' * self.model.size)
        self.assertEqual(self.run_check()['models'][0]['file'], 'sha256_mismatch')
        self.assertFalse(self.servers)

    def test_unpinned_local_model_is_allowed(self):
        local = Model('Local', self.path.stat().st_size, self.path, available=True)
        self.assertEqual(self.run_check([local])['exit_code'], 0)

    def test_models_are_checked_sequentially_on_same_strict_port(self):
        result = self.run_check([self.model, self.model])
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(self.stopped, [38400, 38400])

    def test_failed_load_stops_only_launched_process(self):
        result = self.run_check(health=lambda s, t: False)
        self.assertEqual(result['models'][0]['load'], 'timeout_or_crash')
        self.assertEqual(self.stopped, [38400])
        self.assertTrue(all(not path.exists() for path in self.key_files))

    def test_warmup_timeout_is_failure_and_cleans_up(self):
        def timeout(*args):
            raise TimeoutError('not included in receipt')
        result = self.run_check(warmup=timeout)
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['models'][0]['detail'], 'TimeoutError')
        self.assertEqual(self.stopped, [38400])

    def test_total_deadline_includes_health_and_warmup(self):
        ticks = iter([0, 0, 1, 20])
        result = self.run_check(clock=lambda: next(ticks), timeout=10)
        self.assertEqual(result['models'][0]['warmup'], 'timeout')
        self.assertEqual(result['exit_code'], 1)

    def test_empty_warmup_is_failure(self):
        result = self.run_check(warmup=lambda *args: ' \n')
        self.assertEqual(result['models'][0]['warmup'], 'empty')
        self.assertEqual(result['exit_code'], 1)

    def test_known_bad_fixtures_fail(self):
        fixtures = ['Normal text about GPUs. ' * 100 + '-@' + '@' * 3551,
                    '8' * 200, 'asks8alion' * 120,
                    'A normal prose response. ' + 'asks8alion' * 8]
        for text in fixtures:
            with self.subTest(length=len(text)):
                result = self.run_check(warmup=lambda *args: text)
                self.assertEqual(result['models'][0]['warmup'], 'garbled')
                self.assertEqual(result['exit_code'], 1)

    def test_known_good_formats_pass(self):
        fixtures = ['Ordinary prose about a graphics card.', '-' * 80, '|---' * 9,
                    '1. First\n2. Second\n3. Third', 'ha ha ha ha',
                    'Una tarjeta gráfica procesa muchos píxeles en paralelo.',
                    '图形处理器可以并行处理许多像素。', 'GPUは多くの画素を並列処理します。',
                    '```python\nfor i in range(10):\n    print(i)\n```', 'E = mc^2; x + y = 10']
        for text in fixtures:
            with self.subTest(text=text):
                self.assertEqual(self.run_check(warmup=lambda *args: text)['exit_code'], 0)

    def test_occupied_port_never_launches_or_changes_port(self):
        seen = []
        result = self.run_check(free=lambda port: seen.append(port) or False)
        self.assertEqual(result['models'][0]['load'], 'port_occupied')
        self.assertEqual(seen, [38400])
        self.assertFalse(self.servers)

    def test_protected_or_out_of_range_port_refused_without_socket(self):
        with patch('socket.socket', side_effect=AssertionError('must not open')):
            for port in [1234, 1235, 1236, 1237, 8765, 8767, 11434, 41484, 38399, 38500]:
                with self.subTest(port=port):
                    self.assertFalse(preflight_port_free(port))
                    with self.assertRaises(ValueError):
                        Preflight([self.model], None, self.root, port=port)

    def test_disk_fail_prevents_load(self):
        result = self.run_check(disk=lambda p: SimpleNamespace(free=1))
        self.assertEqual(result['exit_code'], 1)
        self.assertFalse(self.servers)

    def test_disk_warn_still_loads(self):
        result = self.run_check(disk=lambda p: SimpleNamespace(free=100 * 1024 * 1024))
        self.assertEqual(result['status'], 'WARN')
        self.assertEqual(result['exit_code'], 0)

    def test_memory_failure_before_load_prevents_launch(self):
        result = self.run_check(memory=lambda: headroom(100, 4, 'fake'))
        self.assertEqual(result['exit_code'], 1)
        self.assertFalse(self.servers)

    def test_memory_failure_after_load_skips_prompt_and_cleans_up(self):
        counters = iter([headroom(100, 50, 'fake'), headroom(100, 4, 'fake')])
        result = self.run_check(memory=lambda: next(counters),
                                warmup=lambda *args: self.fail('must not generate'))
        self.assertEqual(result['models'][0]['warmup'], 'memory_headroom_failed')
        self.assertEqual(self.stopped, [38400])

    def test_unknown_memory_is_explicit_warning(self):
        result = self.run_check(memory=lambda: headroom(0, 0, 'fake unavailable'))
        self.assertEqual(result['status'], 'WARN')
        self.assertIsNone(result['checks'][2]['free_percent'])

    def test_offline_state_is_honest_without_enabling_downloads(self):
        result = self.run_check(offline=False)
        self.assertFalse(result['offline'])
        self.assertEqual(result['downloads'], 'disabled')

    def test_no_models_is_failure(self):
        self.assertEqual(self.run_check([])['exit_code'], 1)

    def test_missing_binary_does_not_launch(self):
        result = self.run_check(launcher=None)
        self.assertEqual(result['models'][0]['load'], 'missing_binary')

    def test_timeout_must_be_finite_positive(self):
        for timeout in [0, -1, float('inf'), float('nan')]:
            with self.assertRaises(ValueError):
                Preflight([self.model], None, self.root, timeout=timeout)


class MemoryCounterTests(unittest.TestCase):
    def test_threshold_boundaries(self):
        for free, status in [(0, 'FAIL'), (4, 'FAIL'), (5, 'WARN'), (14, 'WARN'), (15, 'PASS')]:
            with self.subTest(free=free):
                self.assertEqual(headroom(100, free, 'fake')['status'], status)
        self.assertEqual(headroom(0, 0, 'fake')['status'], 'UNKNOWN')
        self.assertEqual(headroom(100, 101, 'fake')['status'], 'UNKNOWN')

    def test_nvidia_uses_tightest_reported_device(self):
        def runner(cmd, **kwargs):
            self.assertEqual(cmd[0], 'nvidia-smi')
            return SimpleNamespace(returncode=0, stdout=b'1000, 500\n2000, 80\n')
        result = memory_headroom('cuda', runner=runner)
        self.assertEqual(result['free_percent'], 4)
        self.assertEqual(result['status'], 'FAIL')

    def test_nvidia_missing_is_unknown(self):
        def missing(*args, **kwargs):
            raise FileNotFoundError()
        self.assertEqual(memory_headroom('cuda', runner=missing)['status'], 'UNKNOWN')

    def test_darwin_unified_memory_from_vm_stat(self):
        def runner(cmd, **kwargs):
            output = b'100000\n' if cmd[0] == 'sysctl' else (
                b'Mach Virtual Memory Statistics: (page size of 1000 bytes)\n'
                b'Pages free: 3.\nPages inactive: 10.\nPages speculative: 2.\n')
            return SimpleNamespace(returncode=0, stdout=output)
        result = memory_headroom('metal', runner=runner, system='Darwin')
        self.assertEqual(result['free_percent'], 15)
        self.assertEqual(result['status'], 'PASS')
        self.assertIn('unified', result['source'])

    def test_darwin_malformed_is_unknown(self):
        runner = lambda *a, **k: SimpleNamespace(returncode=0, stdout=b'garbage')
        self.assertEqual(memory_headroom('metal', runner=runner, system='Darwin')['status'], 'UNKNOWN')

    def test_amdgpu_vram_readonly_best_effort(self):
        with tempfile.TemporaryDirectory() as root:
            device = Path(root) / 'card0' / 'device'
            device.mkdir(parents=True)
            (device / 'mem_info_vram_total').write_text('1000')
            (device / 'mem_info_vram_used').write_text('900')
            result = memory_headroom('vulkan', system='Linux', sysfs=Path(root))
            self.assertEqual(result['free_percent'], 10)
            self.assertEqual(result['status'], 'WARN')

    def test_unavailable_amd_is_unknown(self):
        with tempfile.TemporaryDirectory() as root:
            result = memory_headroom('vulkan', system='Linux', sysfs=Path(root))
            self.assertEqual(result['status'], 'UNKNOWN')

    def test_guard_import_is_preferred_when_available(self):
        fake = SimpleNamespace(garble_reason=lambda text: 'repeat_char')
        with patch.dict('sys.modules', {'gpu_link_guard': fake}):
            self.assertEqual(preflight_garble_reason('anything'), 'repeat_char')


class HttpDeadlineTests(unittest.TestCase):
    """Fire fake timers during blocking operations; no thread or socket is opened."""
    def setUp(self):
        self.timers = []
        self.socket = SimpleNamespace(shutdown_calls=[])
        self.socket.shutdown = lambda how: self.socket.shutdown_calls.append(how)
        self.connection = SimpleNamespace(sock=None, connects=0, requests=[], closes=0)

        def connect():
            self.connection.connects += 1
            self.connection.sock = self.socket
        self.connection.connect = connect
        self.connection.request = lambda *a, **k: self.connection.requests.append(a)
        self.connection.close = lambda: setattr(self.connection, 'closes', self.connection.closes + 1)
        self.response = SimpleNamespace(status=200, read=lambda limit: b'{"choices":[{"message":{"content":"GPU renders frames."}}]}')
        self.connection.getresponse = lambda: self.response
        test = self
        class FakeTimer:
            def __init__(self, seconds, callback):
                self.seconds, self.callback = seconds, callback
                self.started = self.cancelled = False
                test.timers.append(self)
            def start(self):
                self.started = True
            def cancel(self):
                self.cancelled = True
            def fire(self):
                self.callback()
        self.http_patch = patch('gpu_link_health.http.client.HTTPConnection', return_value=self.connection)
        self.timer_patch = patch('gpu_link_health.threading.Timer', FakeTimer)
        self.http = self.http_patch.start()
        self.timer_patch.start()
        self.addCleanup(self.http_patch.stop)
        self.addCleanup(self.timer_patch.stop)

    def test_success_arms_daemon_timer_then_cancels_and_closes(self):
        with _http_deadline(38400, 2) as connection:
            self.assertIs(connection, self.connection)
            self.assertTrue(self.timers[0].started)
            self.assertTrue(self.timers[0].daemon)
        self.assertEqual(self.connection.connects, 1)
        self.assertEqual(self.connection.closes, 1)
        self.assertTrue(self.timers[0].cancelled)
        self.assertFalse(self.socket.shutdown_calls)
        self.http.assert_called_once_with('127.0.0.1', 38400, timeout=2)

    def test_expired_connection_is_never_yielded_or_reconnected(self):
        original = self.connection.connect
        def expire_during_connect():
            original()
            self.timers[0].fire()
        self.connection.connect = expire_during_connect
        with self.assertRaises(TimeoutError):
            with _http_deadline(38400, 2):
                self.fail('expired connection must never be exposed to caller')
        self.assertEqual(self.connection.connects, 1)
        self.assertFalse(self.connection.requests)
        self.assertTrue(self.timers[0].cancelled)
        self.assertEqual(self.connection.closes, 1)

    def test_connect_failure_cancels_timer_and_closes(self):
        def fail():
            raise OSError('fake connect failure')
        self.connection.connect = fail
        with self.assertRaises(OSError):
            with _http_deadline(38400, 2):
                self.fail('must not yield failed connection')
        self.assertTrue(self.timers[0].cancelled)
        self.assertEqual(self.connection.closes, 1)

    def test_caller_failure_cancels_timer_and_closes_without_reconnect(self):
        with self.assertRaises(ValueError):
            with _http_deadline(38400, 2):
                raise ValueError('fake parser failure')
        self.assertEqual(self.connection.connects, 1)
        self.assertTrue(self.timers[0].cancelled)
        self.assertEqual(self.connection.closes, 1)

    def test_absolute_deadline_interrupts_body_after_http_connection_detaches_socket(self):
        def detached_response():
            # HTTPConnection does this on HTTP/1.0 / Connection: close responses.
            # The response's buffered reader still owns the original socket.
            self.connection.sock = None
            return self.response
        self.connection.getresponse = detached_response
        def slow_body(limit):
            self.timers[0].fire()
            self.assertTrue(self.socket.shutdown_calls, 'deadline must shutdown buffered response socket')
            raise TimeoutError('blocked reader interrupted')
        self.response.read = slow_body
        with self.assertRaises(TimeoutError):
            warmup_text(SimpleNamespace(port=38400, alias='fake'), 'fake-in-memory-key', 2)
        self.assertEqual(len(self.socket.shutdown_calls), 1)
        self.assertTrue(self.timers[0].cancelled)
        self.assertEqual(self.connection.closes, 1)
        self.assertEqual(self.connection.connects, 1)

    def test_health_deadline_returns_false_and_closes(self):
        def slow_health(limit):
            self.timers[0].fire()
            raise TimeoutError('health reader interrupted')
        self.response.read = slow_health
        self.assertFalse(server_healthy(38400, 2))
        self.assertTrue(self.socket.shutdown_calls)
        self.assertTrue(self.timers[0].cancelled)
        self.assertEqual(self.connection.closes, 1)
        self.assertEqual(self.connection.requests, [('GET', '/health')])

    def test_protected_port_does_not_construct_connection_or_timer(self):
        with self.assertRaises(ValueError):
            with _http_deadline(1235, 2):
                self.fail('must not access protected listener')
        self.http.assert_not_called()
        self.assertFalse(self.timers)


class PortAvailabilityTests(unittest.TestCase):
    def check_ipv6_error(self, error):
        ipv4, ipv6 = MagicMock(), MagicMock()
        ipv4.__enter__.return_value = ipv4
        ipv6.__enter__.return_value = ipv6
        ipv6.bind.side_effect = OSError(error, 'fake IPv6 bind failure')
        with patch('gpu_link_health.socket.has_ipv6', True), \
                patch('gpu_link_health.socket.socket', side_effect=[ipv4, ipv6]) as factory:
            result = preflight_port_free(38400)
        ipv4.bind.assert_called_once_with(('127.0.0.1', 38400))
        ipv6.bind.assert_called_once_with(('::1', 38400))
        ipv4.connect.assert_not_called()
        ipv6.connect.assert_not_called()
        self.assertEqual(factory.call_args_list[0].args, (socket.AF_INET, socket.SOCK_STREAM))
        self.assertEqual(factory.call_args_list[1].args, (socket.AF_INET6, socket.SOCK_STREAM))
        return result

    def test_ipv6_only_foreign_listener_refuses_port(self):
        self.assertFalse(self.check_ipv6_error(errno.EADDRINUSE))

    def test_unavailable_ipv6_does_not_block_free_ipv4_port(self):
        self.assertTrue(self.check_ipv6_error(errno.EAFNOSUPPORT))

    def test_ipv6_permission_failure_fails_closed(self):
        self.assertFalse(self.check_ipv6_error(errno.EPERM))


if __name__ == '__main__':
    unittest.main()

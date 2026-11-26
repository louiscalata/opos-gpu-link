# SPDX-License-Identifier: Apache-2.0
"""CLI configuration, receipts and ownership lifecycle using fakes only."""
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gpu_link_health as h


class HealthCliTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'small.gguf'
        self.path.write_bytes(b'weights')
        self.binary = self.root / 'llama-server'
        self.binary.write_text('fake binary')
        self.model = h.Model('Small', 7, self.path)
        self.config = self.root / 'models.json'
        self.receipt = self.root / 'receipt.json'

    def config_file(self, rows):
        self.config.write_text(json.dumps(rows))
        return self.config

    def args(self, **overrides):
        values = dict(binary=self.binary, port=38400, log_dir=self.root / 'logs',
                      timeout=1, interval=0.1, duration=0.3, backend='cpu', offline=True)
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_model_paths_are_local_snapshots_not_yet_verified(self):
        model = h.configured_models([self.path])[0]
        self.assertEqual(model.size, 7)
        self.assertFalse(model.available)
        self.assertFalse(model.known_good)

    def test_json_paths_are_relative_to_configuration(self):
        path = self.config_file([{'path': 'small.gguf', 'name': 'Local', 'known_good': True}])
        model = h.configured_models(models_file=path)[0]
        self.assertEqual(model.path, self.path)
        self.assertEqual(model.name, 'Local')
        self.assertTrue(model.known_good)

    def test_missing_file_is_representable_for_preflight_failure(self):
        model = h.configured_models([self.root / 'missing.gguf'])[0]
        self.assertEqual(model.size, 1)
        self.assertFalse(model.available)

    def test_pinned_filename_supplies_exact_size_and_sha(self):
        import gpu_link_pins as pins
        pin = {'file': 'small.gguf', 'size': 7, 'sha256': 'a' * 64, 'label': 'Pinned'}
        with patch.object(pins, 'MODELS', (pin,)), patch.object(pins, 'RX580_MODELS', ()):
            model = h.configured_models([self.path])[0]
        self.assertEqual((model.size, model.sha256, model.name), (7, 'a' * 64, 'Pinned'))
        self.assertTrue(model.known_good)

    def test_config_cannot_override_pinned_size_or_sha(self):
        import gpu_link_pins as pins
        pin = {'file': 'small.gguf', 'size': 7, 'sha256': 'a' * 64, 'label': 'Pinned'}
        for override in ({'size': 1}, {'sha256': 'b' * 64}):
            with self.subTest(override=override):
                config = self.config_file([dict(path='small.gguf', **override)])
                with patch.object(pins, 'MODELS', (pin,)), patch.object(pins, 'RX580_MODELS', ()):
                    with self.assertRaises(ValueError):
                        h.configured_models(models_file=config)

    def test_malformed_rows_are_refused(self):
        for rows in ({'path': 'small.gguf'}, ['small.gguf'], [{'path': ''}],
                     [{'path': 'small.gguf', 'size': True}],
                     [{'path': 'small.gguf', 'sha256': 'invalid'}],
                     [{'path': 'small.gguf', 'known_good': 'yes'}]):
            with self.subTest(rows=rows):
                with self.assertRaises(ValueError):
                    h.configured_models(models_file=self.config_file(rows))

    def test_duplicate_model_path_refused(self):
        with self.assertRaises(ValueError):
            h.configured_models([self.path, self.path])

    def test_watch_verifies_size_sha_before_spawn(self):
        for model in (h.Model('Wrong size', 8, self.path),
                      h.Model('Wrong sha', 7, self.path, sha256='a' * 64)):
            factory = unittest.mock.Mock()
            with self.assertRaises(ValueError):
                h.run_watch(self.args(), [model], watchdog_factory=factory)
            factory.assert_not_called()

    def test_watch_disabled_starts_no_process(self):
        factory = unittest.mock.Mock()
        with patch.dict(os.environ, {'OPOS_GPU_LINK_WATCHDOG': '0'}):
            result = h.run_watch(self.args(binary=None), [], watchdog_factory=factory)
        self.assertEqual(result['status'], 'DISABLED')
        factory.assert_not_called()

    def test_watch_enforces_binary_and_port_capacity_before_spawn(self):
        for args, models in ((self.args(binary=None), [self.model]),
                             (self.args(port=38499), [self.model, self.model]),
                             (self.args(), [])):
            factory = unittest.mock.Mock()
            with self.assertRaises(ValueError):
                h.run_watch(args, models, watchdog_factory=factory)
            factory.assert_not_called()

    def test_watch_direct_api_refuses_protected_port_before_spawn(self):
        factory = unittest.mock.Mock()
        with self.assertRaises(ValueError):
            h.run_watch(self.args(port=1235), [self.model], watchdog_factory=factory)
        factory.assert_not_called()

    def fake_setup(self):
        import gpu_link_autosetup as setup
        return SimpleNamespace(write_key_file=setup.write_key_file,
                               runtime_env=lambda binary: {'TEST_RUNTIME': 'captured'},
                               moltenvk_env=lambda env, binary: env,
                               server_command=setup.server_command)

    def fake_watchdog(self, fail_second=False, give_up=False):
        owner = self
        class FakeWatchdog:
            def __init__(self, **kwargs):
                self.servers, self.calls, self.closed = [], [], False
                self.notify = kwargs['notify']
                owner.watchdog = self
            def spawn(self, command, port, **options):
                if fail_second and self.servers:
                    raise ValueError('fake bind failure')
                key = Path(command[command.index('--api-key-file') + 1])
                owner.assertTrue(key.is_file())
                self.calls.append((command, port, options, key))
                process = SimpleNamespace(returncode=None)
                process.poll = lambda p=process: p.returncode
                self.servers.append(SimpleNamespace(gave_up=give_up, process=process))
            def tick(self):
                return []
            def close(self):
                for command, port, options, key in self.calls:
                    owner.assertTrue(key.is_file())
                    owner.assertFalse(options['stdout'].closed)
                for server in self.servers:
                    server.process.returncode = 0
                self.closed = True
        return FakeWatchdog

    def test_watch_closes_children_before_private_key_and_logs(self):
        ticks = [0.0]
        def sleep(seconds):
            ticks[0] += seconds
        result = h.run_watch(self.args(), [self.model], watchdog_factory=self.fake_watchdog(),
                             setup_module=self.fake_setup(), clock=lambda: ticks[0], sleep=sleep)
        self.assertEqual(result['status'], 'STOPPED')
        self.assertIn('NOT_VERIFIED', result['model_readiness'])
        self.assertTrue(self.watchdog.closed)
        self.assertTrue(result['owned_servers_exited'])
        command, port, options, key = self.watchdog.calls[0]
        self.assertEqual(port, 38400)
        self.assertEqual(options['env'], {'TEST_RUNTIME': 'captured'})
        self.assertFalse(key.exists())
        self.assertTrue(options['stdout'].closed)
        self.assertNotIn('Bearer', json.dumps(result))

    def test_watch_partial_launch_failure_cleans_first_process(self):
        with self.assertRaises(ValueError):
            h.run_watch(self.args(), [self.model, self.model],
                        watchdog_factory=self.fake_watchdog(fail_second=True), setup_module=self.fake_setup())
        self.assertTrue(self.watchdog.closed)
        self.assertFalse(self.watchdog.calls[0][-1].exists())

    def test_watch_reports_gave_up_as_failure(self):
        result = h.run_watch(self.args(), [self.model], watchdog_factory=self.fake_watchdog(give_up=True),
                             setup_module=self.fake_setup())
        self.assertEqual((result['status'], result['exit_code']), ('FAIL', 1))
        self.assertTrue(self.watchdog.closed)

    def test_main_prints_table_and_writes_json_receipt(self):
        fake = {'status': 'PASS', 'exit_code': 0, 'checks': [], 'models': []}
        with patch.object(h, 'Preflight') as check, contextlib.redirect_stdout(io.StringIO()) as output:
            check.return_value.run.return_value = fake
            result = h.main(['preflight', '--model-path', str(self.path), '--receipt', str(self.receipt)])
        self.assertEqual(result, 0)
        self.assertEqual(json.loads(self.receipt.read_text())['mode'], 'preflight')
        self.assertIn('CHECK', output.getvalue())
        self.assertIn('PASS', output.getvalue())

    def test_main_reports_offline_environment(self):
        with patch.dict(os.environ, {'OPOS_GPU_LINK_OFFLINE': 'true'}), patch.object(h, 'Preflight') as check:
            check.return_value.run.return_value = {'status': 'PASS', 'exit_code': 0}
            with contextlib.redirect_stdout(io.StringIO()):
                h.main(['preflight', '--receipt', str(self.receipt)])
        self.assertTrue(check.call_args.args[4])

    def test_main_sanitizes_errors_in_output_and_receipt(self):
        secret = 'never-echo-this-secret'
        with patch.object(h, 'configured_models', side_effect=ValueError(secret)), contextlib.redirect_stdout(io.StringIO()) as output:
            result = h.main(['watch', '--receipt', str(self.receipt)])
        self.assertEqual(result, 1)
        self.assertNotIn(secret, output.getvalue() + self.receipt.read_text())
        self.assertEqual(json.loads(self.receipt.read_text())['error'], 'ValueError')

    def test_main_validates_finite_options_before_any_launch(self):
        for option, value in (('--port', '1235'), ('--timeout', 'nan'), ('--timeout', '0'),
                              ('--duration', 'inf'), ('--duration', '-1'), ('--interval', '0.01')):
            with self.subTest(option=option, value=value), patch.object(h, 'configured_models') as configured:
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                    h.main(['watch', option, value])
                configured.assert_not_called()


if __name__ == '__main__':
    unittest.main()

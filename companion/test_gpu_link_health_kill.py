# SPDX-License-Identifier: Apache-2.0
"""Opt-in real subprocess crash test, restricted to our exact D port.

OPOS_GPU_LINK_REAL_KILL_TEST=1 python3 -B -m unittest test_gpu_link_health_kill -v
Ordinary discovery runs no server: all policy tests use injected fakes.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import unittest

from gpu_link_health import Watchdog, server_healthy


FAKE_HTTP_SERVER = r'''
import argparse
import http.server
p = argparse.ArgumentParser()
p.add_argument('--host', required=True)
p.add_argument('--port', type=int, required=True)
a = p.parse_args()
assert a.host == '127.0.0.1' and 38400 <= a.port <= 38499
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == '/health' else 404)
        self.send_header('Content-Length', '2')
        self.end_headers()
        self.wfile.write(b'{}')
    def log_message(self, *args):
        pass
http.server.HTTPServer.allow_reuse_address = True
http.server.HTTPServer((a.host, a.port), Handler).serve_forever()
'''


def listeners():
    """Names, PID and endpoints only; never inspect any process arguments."""
    result = subprocess.run(['lsof', '-nP', '-iTCP', '-sTCP:LISTEN'],
                            capture_output=True, text=True, timeout=5)
    if result.returncode not in (0, 1):
        raise RuntimeError('listener inventory unavailable')
    return sorted(' '.join((parts[0], parts[1], parts[-2]))
                  for line in result.stdout.splitlines()[1:]
                  if len(parts := line.split()) >= 9)


@unittest.skipUnless(os.environ.get('OPOS_GPU_LINK_REAL_KILL_TEST') == '1',
                     'opt-in real subprocess test; standard suite uses fakes only')
class RealKillTest(unittest.TestCase):
    def test_own_fake_http_server_crash_restarts_and_cleans_up(self):
        port = 38471
        receipt = {'port': port, 'server': 'tiny fake HTTP subprocess; no model/GPU',
                   'status': 'NOT_RUN', 'restarted': False}
        destination = Path(os.environ.get('OPOS_GPU_LINK_KILL_RECEIPT',
                           '../receipts/guard-health/real-kill.json'))
        watch = None
        before = listeners()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                try:
                    probe.bind(('127.0.0.1', port))
                except PermissionError:
                    receipt['reason'] = 'sandbox denied loopback bind (EPERM); no child started'
                    self.skipTest(receipt['reason'])
                except OSError:
                    receipt['reason'] = 'strict test port already occupied; no child started'
                    self.skipTest(receipt['reason'])
            receipt['status'] = 'FAIL'
            watch = Watchdog(backoff=0.01, startup_grace=0, enabled=True)
            command = [sys.executable, '-B', '-u', '-c', FAKE_HTTP_SERVER,
                       '--host', '127.0.0.1', '--port', str(port)]
            server = watch.spawn(command, port)
            def ready():
                end = time.monotonic() + 5
                while time.monotonic() < end:
                    if server_healthy(port, timeout=0.2):
                        return True
                    if server.process.poll() is not None:
                        return False
                    time.sleep(0.02)
                return False
            self.assertTrue(ready(), 'our fake server did not become healthy')
            old = server.process
            receipt['initial_pid'] = old.pid
            old.kill()  # Only this test's own Popen, never a discovered PID.
            old.wait(timeout=3)
            self.assertEqual(watch.tick()[0]['status'], 'restart_pending')
            time.sleep(0.03)
            self.assertEqual(watch.tick()[0]['status'], 'restarted')
            self.assertNotEqual(server.process.pid, old.pid)
            self.assertTrue(ready(), 'restarted fake server did not become healthy')
            receipt.update(restarted=True, restarted_pid=server.process.pid, status='PASS')
        finally:
            if watch is not None:
                watch.close()
                receipt['owned_children_exited'] = all(s.process.poll() is not None for s in watch.servers)
            after = listeners()
            receipt['listener_list_unchanged'] = before == after
            receipt['listeners_added'] = sorted(set(after) - set(before))
            receipt['listeners_removed'] = sorted(set(before) - set(after))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(receipt, indent=2) + '\n')
            self.assertEqual(before, after, 'listener list changed during isolated kill test')


if __name__ == '__main__':
    unittest.main()

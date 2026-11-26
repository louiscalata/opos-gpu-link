# SPDX-License-Identifier: Apache-2.0
"""A model server that stalls or crashes mid-answer pauses the answer and resumes it, not fails it."""
from __future__ import annotations

import http.client
import unittest
from unittest.mock import patch

import gpu_link_worker as worker
import opos_gpu_link as link

FIRST = "Section 1: reproduce the failing test locally. "
REST = "Section 2: read the auth logs. Section 3: fix the token clock."


class Phone:
    """Just enough of the phone service: a lease-less status twice pauses; a paused answer is re-offered."""

    def __init__(self):
        self.state, self.text, self.lease, self.misses = "waiting", "", None, 0
        self.leases, self.errors, self.status_states, self.offers = 0, [], [], []
        self.epoch = b"epoch"

    def status(self, lease=None, tokens=None, tps=None, error=None, state=None):
        self.status_states.append(state)
        if error is not None:
            if lease == self.lease:
                self.state, self.lease = "failed", None
                self.errors.append(error)
            return 200, {"cancel": None}
        if self.lease is not None and lease != self.lease:
            self.misses += 1
            if self.misses >= 2:
                self.state, self.lease, self.misses = "paused", None, 0
        return 200, {"cancel": None}

    def send(self, method, target, raw=b""):
        if method == "GET":
            if self.state not in ("waiting", "paused", "answering") or self.state == "answering" and self.lease:
                return 204, {}
            self.leases += 1
            self.lease = f"{self.leases:032x}"
            self.state, self.misses = "answering", 0
            self.offers.append(self.text)
            return 200, {"lease": self.lease, "partial": self.text, "question": "Debug a failing auth test",
                         "model_id": "lead"}
        body = worker.proto.loads(raw, worker.proto.TEXT_BODY_LIMIT)
        if target != f"/v1/runs/{self.lease}/text":
            return 404, {"error": "lease"}
        self.text += body["text"]
        if body["done"]:
            self.state, self.lease = "done", None
        return 200, {"acked": len(self.text.encode())}


class Source:
    def __init__(self, data, error, done=True):
        self.data, self.error, self.done = data.encode(), error, done
        self.error_code = "server"

    def snapshot(self):
        return self.data, self.done, "stop", None, self.error

    def close(self):
        pass


def drive(reactor, clock, until, limit=400):
    for _ in range(limit):
        if until():
            return True
        reactor.step()
        clock[0] += 0.25
    return until()


class ServerStallTests(unittest.TestCase):
    def setUp(self):
        self.clock = [0.0]
        self.phone = Phone()
        self.ready = [False]
        self.jobs = []

        def factory(job):
            self.jobs.append(job)
            if len(self.jobs) == 1:
                return Source(FIRST, error=False, done=False)  # streams, then the server stalls
            return Source(job["partial"] + REST, error=False)

        self.reactor = worker.StandIn(self.phone, factory, rate=4, emit=lambda _line: None,
                                      clock=lambda: self.clock[0], give_up_after=30,
                                      server_ready=lambda: self.ready[0])

    def test_stall_pauses_then_resumes_from_the_acknowledged_text(self):
        self.assertTrue(drive(self.reactor, self.clock, lambda: self.phone.text == FIRST))
        self.reactor.source.error = True  # the stream times out: the server stopped answering
        self.assertTrue(drive(self.reactor, self.clock, lambda: self.phone.state == "paused"))
        self.assertEqual(self.phone.errors, [])
        self.assertIn("loading", self.phone.status_states)  # the phone sees the MacBook warming, not failed
        self.clock[0] += 30
        drive(self.reactor, self.clock, lambda: False, limit=20)
        self.assertEqual(self.phone.state, "paused")  # never asked again while the server is down
        self.assertEqual(len(self.jobs), 1)
        self.ready[0] = True
        self.assertTrue(drive(self.reactor, self.clock, lambda: self.phone.state == "done"))
        self.assertEqual(self.phone.offers, ["", FIRST])
        self.assertEqual(self.jobs[1]["partial"], FIRST)
        self.assertEqual(self.phone.text, FIRST + REST)
        self.assertEqual(self.phone.errors, [])
        self.assertIsNone(self.reactor.recovery)

    def test_a_server_that_never_answers_is_asked_again_after_the_hold_limit(self):
        self.assertTrue(drive(self.reactor, self.clock, lambda: self.phone.text == FIRST))
        self.reactor.source.error = True
        self.assertTrue(drive(self.reactor, self.clock, lambda: self.phone.state == "paused"))
        self.clock[0] += worker.RECOVERY_MAX_HOLD
        self.assertTrue(drive(self.reactor, self.clock, lambda: self.phone.state == "done"))
        self.assertEqual(self.phone.errors, [])

    def test_repeated_failures_without_progress_end_in_the_error(self):
        def failing(job):
            self.jobs.append(job)
            return Source(job["partial"], error=True)

        self.reactor.source_factory = failing
        self.ready[0] = True
        self.assertTrue(drive(self.reactor, self.clock, lambda: self.phone.state == "failed", limit=2000))
        self.assertEqual(self.phone.errors, ["server"])
        self.assertEqual(len(self.jobs), worker.RECOVERY_TRIES + 1)

    def test_garbled_and_model_errors_still_fail_at_once(self):
        for code in ("garbled", "model", "fallback_failed", "model_start"):
            phone = Phone()

            def factory(job, code=code):
                source = Source(job["partial"], error=True)
                source.error_code = code
                return source

            clock = [0.0]
            reactor = worker.StandIn(phone, factory, emit=lambda _line: None, clock=lambda: clock[0],
                                     server_ready=lambda: True)
            self.assertTrue(drive(reactor, clock, lambda: phone.state == "failed"), code)
            self.assertEqual(phone.errors, [code])
            self.assertEqual(phone.leases, 1, code)
            self.assertNotIn("loading", phone.status_states, code)


class HoldBookkeepingTests(unittest.TestCase):
    def test_slow_probe_is_spaced_from_its_end(self):
        clock, probes = [0.0], []

        def slow_probe():
            probes.append(clock[0])
            clock[0] += 1.5  # a hung server times the probe out
            return False

        reactor = worker.StandIn(Phone(), emit=lambda _line: None, clock=lambda: clock[0], server_ready=slow_probe)
        reactor.holding_since = 0.0
        clock[0] = worker.RECOVERY_MIN_HOLD
        for _ in range(60):
            reactor._recovered()
            clock[0] += 0.1
        gaps = [b - a for a, b in zip(probes, probes[1:])]
        self.assertTrue(gaps and all(gap >= 2.5 - 1e-9 for gap in gaps), gaps)

    def test_cancel_or_a_new_run_resets_the_budget(self):
        reactor = worker.StandIn(Phone(), emit=lambda _line: None, clock=lambda: 0.0)
        reactor.recovery = ("Q", worker.RECOVERY_TRIES, 50)
        reactor.pc.send = lambda *_args: (200, {"lease": "1" * 32, "partial": "", "question": "Q"})
        reactor.source_factory = lambda job: Source(job["partial"], error=False, done=False)
        reactor._work()
        self.assertIsNone(reactor.recovery)
        reactor.recovery = ("Q", 2, 0)
        reactor.pc.status = lambda *_args, **_kwargs: (200, {"cancel": reactor.job["lease"]})
        reactor._status()
        self.assertIsNone(reactor.recovery)


class ServerAnswersTests(unittest.TestCase):
    def fake(self, behaviour):
        class Response:
            def __init__(self, status):
                self.status = status

            def read(self, _n):
                return b""

        class Connection:
            def __init__(self, *_args, **_kwargs):
                pass

            def request(self, *_args, **_kwargs):
                if behaviour == "hang":
                    raise TimeoutError("timed out")

            def getresponse(self):
                return Response(behaviour)

            def close(self):
                pass

        return Connection

    def test_health_probe(self):
        for behaviour, expected in ((200, True), (404, True), (503, False), ("hang", False)):
            with patch.object(link.http.client, "HTTPConnection", self.fake(behaviour)):
                self.assertEqual(link.model_server_answers("http://127.0.0.1:38400/v1/chat/completions"),
                                 expected, behaviour)


if __name__ == "__main__":
    unittest.main()

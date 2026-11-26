"""Guard wiring with in-memory HTTP/SSE fakes: no network, GPU or phone."""
from __future__ import annotations

import json
import os
import threading
import unittest
from unittest.mock import patch

import gpu_link_worker as worker
import opos_gpu_link as link


URL = "http://127.0.0.1:38101/v1/chat/completions"
PROSE = "A GPU transforms vertices, shades fragments, and presents a completed frame. "


def event(text: str, model: str = "model", finish: str | None = None) -> bytes:
    value = {"model": model, "choices": [{"delta": {"content": text}, "finish_reason": finish}]}
    return b"data: " + json.dumps(value).encode() + b"\n"


def answer(text: str, model: str = "model") -> list[bytes]:
    return [event(text, model), event("", model, "stop"), b"data: [DONE]\n"]


class FakeResponse:
    status = 200

    def __init__(self, lines: list[bytes]):
        self.lines = lines
        self.read_count = 0
        self.closed = False

    def getheader(self, name: str, default=None):
        return "text/event-stream" if name == "Content-Type" else default

    def readline(self, _limit: int) -> bytes:
        if self.read_count == len(self.lines):
            return b""
        line = self.lines[self.read_count]
        self.read_count += 1
        return line

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def close(self):
        self.closed = True


class FakeWire:
    def __init__(self):
        self.shutdown_count = 0

    def settimeout(self, _value):
        pass

    def shutdown(self, _how):
        self.shutdown_count += 1


class FakeHTTP:
    """Thread-safe factory whose responder chooses a separate stream per request."""

    def __init__(self, responder):
        self.responder = responder
        self.requests = []
        self.connections = []
        self.responses = []
        self.lock = threading.Lock()

    def __call__(self, host, port, timeout):
        assert (host, port, timeout) == ("127.0.0.1", 38101, 2)
        owner = self

        class Connection:
            sock = FakeWire()
            closed = False
            body = None

            def connect(self):
                pass

            def request(self, method, target, payload, _headers):
                assert (method, target) == ("POST", "/v1/chat/completions")
                self.body = json.loads(payload)
                with owner.lock:
                    owner.requests.append(self.body)
                    self.index = len(owner.requests) - 1

            def getresponse(self):
                response = FakeResponse(owner.responder(self.body, self.index))
                with owner.lock:
                    owner.responses.append(response)
                return response

            def close(self):
                self.closed = True

        connection = Connection()
        self.connections.append(connection)
        return connection


def job(lease: str = "a" * 32, partial: str = "", **extra):
    return {"lease": lease, "question": "Explain a GPU frame.", "partial": partial, **extra}


class GuardStreamTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"OPOS_GPU_LINK_GUARD": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def finish(self, source):
        self.addCleanup(source.close)
        source.worker.join(3)
        self.assertFalse(source.worker.is_alive(), "fake SSE reader did not finish")
        self.assertTrue(source.snapshot()[1])
        return source.snapshot()

    def test_first_garble_closes_early_and_retries_from_trimmed_prefix(self):
        bad = [event(PROSE), event("@" * 200), event("must never be consumed")]
        fake = FakeHTTP(lambda _body, index: bad if index == 0 else answer("The display reads it."))
        with patch.object(worker.http.client, "HTTPConnection", fake):
            source = worker.ServerSource(job(), URL, "model")
            data, _, _, _, error = self.finish(source)
        self.assertFalse(error)
        self.assertEqual(data.decode(), PROSE + "The display reads it.")
        self.assertEqual(len(fake.requests), 2)
        self.assertLess(fake.responses[0].read_count, len(bad))
        self.assertTrue(all(response.closed for response in fake.responses))
        self.assertTrue(all(connection.closed for connection in fake.connections))
        first, retry = fake.requests
        self.assertNotEqual(first["seed"], retry["seed"])
        self.assertLessEqual(retry["temperature"], 0.4)
        self.assertGreaterEqual(retry["repeat_penalty"], 1.1)
        self.assertEqual(retry["top_p"], 0.9)
        self.assertEqual(retry["messages"][-1], {"role": "assistant", "content": PROSE})

    def test_second_garble_is_terminal_and_never_requests_a_third_stream(self):
        fake = FakeHTTP(lambda _body, _index: [event(PROSE), event("asks8alion" * 120), event("unread")])
        with patch.object(worker.http.client, "HTTPConnection", fake):
            source = worker.ServerSource(job(), URL, "model")
            data, _, _, _, error = self.finish(source)
        self.assertTrue(error)
        self.assertEqual(source.error_code, "garbled")
        self.assertEqual(source.guard_reason, "ngram_loop")
        self.assertNotIn(b"asks8alion", data)
        self.assertEqual(len(fake.requests), 2)
        self.assertTrue(all(response.read_count == 2 for response in fake.responses))

    def test_retry_keeps_sampling_values_that_were_already_safer(self):
        fake = FakeHTTP(lambda _body, index: answer("8" * 200) if index == 0 else answer("Finished."))
        settings = {"temperature": 0.2, "repeat_penalty": 1.3, "top_p": 0.98}
        with patch.object(worker.http.client, "HTTPConnection", fake):
            self.finish(worker.ServerSource(job(sampling=settings), URL, "model"))
        self.assertEqual(fake.requests[1]["temperature"], 0.2)
        self.assertEqual(fake.requests[1]["repeat_penalty"], 1.3)
        self.assertEqual(fake.requests[1]["top_p"], 0.9)

    def test_raw_encoding_junk_is_detected_before_control_sanitation(self):
        fake = FakeHTTP(lambda _body, _index: answer(PROSE + "\x00" * 100))
        with patch.object(worker.http.client, "HTTPConnection", fake):
            source = worker.ServerSource(job(), URL, "model")
            data, _, _, _, error = self.finish(source)
        self.assertTrue(error)
        self.assertEqual(source.error_code, "garbled")
        self.assertEqual(source.guard_reason, "encoding_junk")
        self.assertNotIn(b"\x00", data)
        self.assertEqual(len(fake.requests), 2)

    def test_guard_off_keeps_legacy_stream_and_does_not_retry(self):
        bad = PROSE + "@" * 200
        fake = FakeHTTP(lambda _body, _index: answer(bad))
        with patch.dict(os.environ, {"OPOS_GPU_LINK_GUARD": "0"}), \
                patch.object(worker.http.client, "HTTPConnection", fake):
            source = worker.ServerSource(job(), URL, "model")
            data, _, _, _, error = self.finish(source)
        self.assertFalse(error)
        self.assertEqual(data.decode(), bad)
        self.assertEqual(len(fake.requests), 1)

    def test_resume_keeps_retry_budget_and_manual_new_lease_resets_it(self):
        fake = FakeHTTP(lambda _body, _index: answer("8" * 200))
        budget = worker.GuardRetryBudget()
        with patch.object(worker.http.client, "HTTPConnection", fake):
            self.finish(worker.ServerSource(job(), URL, "model", budget))
            self.assertEqual(len(fake.requests), 2)
            resumed = worker.ServerSource(job(partial="Saved safe prefix. "), URL, "model", budget)
            self.finish(resumed)
            self.assertEqual(len(fake.requests), 3)
            self.assertEqual(resumed.error_code, "garbled")
            self.finish(worker.ServerSource(job("b" * 32), URL, "model", budget))
        self.assertEqual(len(fake.requests), 5)
        seeds = [request["seed"] for request in fake.requests]
        self.assertTrue(all(left != right for left, right in zip(seeds, seeds[1:])))

    def test_unicode_byte_limit_keeps_a_valid_bounded_safe_prefix(self):
        # Distinct CJK characters avoid synthetic repeated-phrase heuristics.
        long_text = "".join(chr(0x4E00 + index) for index in range(5000))
        fake = FakeHTTP(lambda _body, _index: answer(long_text))
        with patch.object(worker.http.client, "HTTPConnection", fake):
            source = worker.ServerSource(job(), URL, "model")
            data, _, _, _, error = self.finish(source)
        self.assertTrue(error)
        self.assertEqual(source.error_code, "garbled")
        self.assertEqual(source.guard_reason, "runaway_length")
        self.assertLessEqual(len(data), worker.proto.MAX_ANSWER_BYTES)
        self.assertTrue(data.decode())

    def test_one_bad_lane_does_not_close_or_retry_a_good_lane(self):
        def respond(body, _index):
            return answer("@" * 200, "bad") if body["model"] == "bad" else answer(PROSE, "good")
        fake = FakeHTTP(respond)
        with patch.object(worker.http.client, "HTTPConnection", fake):
            bad = worker.ServerSource(job(), URL, "bad")
            good = worker.ServerSource(job(), URL, "good")
            self.finish(bad)
            data, _, _, _, error = self.finish(good)
        self.assertTrue(bad.snapshot()[-1])
        self.assertFalse(error)
        self.assertEqual(data.decode(), PROSE)
        self.assertEqual([request["model"] for request in fake.requests].count("bad"), 2)
        self.assertEqual([request["model"] for request in fake.requests].count("good"), 1)

    def test_lazy_lane_forwards_garbled_code_and_discards_ready_check(self):
        fake = FakeHTTP(lambda _body, _index: answer("8" * 200))
        checked = {"model"}
        with patch.object(worker.http.client, "HTTPConnection", fake):
            source = link.LazyServerSource(job(), URL, "model", checked, threading.Lock())
            self.addCleanup(source.close)
            source.thread.join(3)
            self.assertIsNotNone(source.source)
            self.finish(source.source)
            self.assertTrue(source.snapshot()[-1])
            self.assertEqual(source.error_code, "garbled")
        self.assertNotIn("model", checked)


class GuardStatusTests(unittest.TestCase):
    def test_safe_prefix_posts_before_garbled_error_without_final_completion(self):
        events = []

        class Phone:
            epoch = b"epoch"

            def send(self, _method, _target, raw):
                body = worker.proto.loads(raw, worker.proto.TEXT_BODY_LIMIT)
                events.append(("text", body))
                return 200, {"acked": body["offset"] + len(body["text"].encode())}

            def status(self, _lease=None, _tokens=None, _tps=None, error=None, state=None):
                events.append(("status", error))
                return 200, {}

        class Failed:
            error_code = "garbled"

            def snapshot(self):
                return (PROSE * 9).encode(), True, "stop", 100, True

            def close(self):
                events.append(("close", None))

        reactor = worker.StandIn(Phone(), emit=lambda _line: None)
        reactor.job = job()
        reactor.source = Failed()
        reactor._status()  # Error must wait until the bounded text posts are acknowledged.
        self.assertFalse(any(kind == "status" and value == "garbled" for kind, value in events))
        for _ in range(12):
            if reactor.job is None:
                break
            reactor._post()
            if reactor.job is not None:
                reactor._status()
        self.assertIsNone(reactor.job)
        texts = [value for kind, value in events if kind == "text"]
        self.assertEqual("".join(body["text"] for body in texts), PROSE * 9)
        self.assertTrue(all(not body["done"] and body["finish"] is None for body in texts))
        garbled_index = next(i for i, item in enumerate(events) if item == ("status", "garbled"))
        self.assertTrue(all(kind != "text" for kind, _value in events[garbled_index + 1:]))


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Per-lane Retry: rerun one lane's current question without touching the others."""

import io
import threading
import unittest
import urllib.request
from copy import deepcopy
from unittest import mock

from opos import ai_answers, ai_page, muse
import json

from tests.ai_page_support import PC, FakeStream, request, running
from tests import test_ai_page as _page


def _models(*panes):
    return [{"pane": pane, "id": f"vendor/{pane}", "label": f"PC {pane}", "maker": "Maker",
             "gpu": None, "live": True, "live_speed": None} for pane in panes]


class LaneRetry(unittest.TestCase):
    setUp = _page.AiPage.setUp
    close_workers = _page.AiPage.close_workers
    job = _page.AiPage.job
    join_workers = _page.AiPage.join_workers
    ask = _page.AiPage.ask

    def retry(self, pane, ident=None, safe=None):
        body = {"action": "retry", "pane": pane}
        if ident is not None:
            body["id"] = ident
        if safe is not None:
            body["safe"] = safe
        return ai_page.post(body)

    def pc(self, *panes):
        self.link.value["pc"] = {**deepcopy(PC), "models": _models(*panes)}

    def test_failed_phone_lane_reruns_the_same_question_with_a_new_answer(self):
        self.job(["Prefix"], RuntimeError("boom"))
        self.ask(question="How does a pc work")
        self.join_workers()
        failed = self.answers.latest("phone")
        self.assertEqual((failed["state"], failed["error"]), ("failed", "stream_error"))
        self.job(["Second try"])
        status, snap = self.retry("phone", failed["id"])
        self.assertEqual(status, 200)
        self.join_workers()
        fresh = self.answers.latest("phone")
        self.assertNotEqual(fresh["id"], failed["id"])
        self.assertEqual((fresh["state"], fresh["text"], fresh["question"]),
                         ("done", "Second try", "How does a pc work"))
        self.assertEqual(self.answers.get(failed["id"])["state"], "failed")  # history kept

    def test_safe_retry_selects_a_fresh_seed_and_safer_completion_payload(self):
        self.job(["first"])
        self.ask(question="Q")
        self.join_workers()
        seeds = []
        with mock.patch.object(ai_page.secrets, "randbits", side_effect=(101, 202)):
            for seed in (101, 202):
                self.job(["safe answer"])
                old = self.answers.latest("phone")["id"]
                self.assertEqual(self.retry("phone", old, safe=1)[0], 200)
                jobs = self.join_workers()
                self.assertEqual(jobs[0].safe_seed, seed)
                opener = muse.stream.call_args.kwargs["opener"]
                request = urllib.request.Request(
                    "http://fixture.invalid/v1/chat/completions",
                    data=json.dumps({"model": "fixture", "messages": [{"role": "user", "content": "Q"}],
                                     "temperature": 0.2, "max_tokens": 4096, "stream": True}).encode(),
                    headers={"Content-Type": "application/json", "Content-Length": "2"}, method="POST")
                with mock.patch.object(muse, "_open_no_redirect", return_value="response") as transport:
                    self.assertEqual(opener(request, timeout=2), "response")
                    transport.assert_called_once_with(request, timeout=2)
                payload = json.loads(request.data)
                self.assertFalse(request.has_header("Content-length"))
                self.assertEqual((payload["seed"], payload["temperature"], payload["repeat_penalty"]),
                                 (seed, 0.1, 1.1))
                self.assertEqual((payload["model"], payload["messages"], payload["max_tokens"], payload["stream"]),
                                 ("fixture", [{"role": "user", "content": "Q"}], 4096, True))
                seeds.append(payload["seed"])
                self.assertEqual(self.answers.latest("phone")["text"], "safe answer")
        self.assertNotEqual(*seeds)

    def test_safe_opener_leaves_model_verification_request_unchanged(self):
        worker = ai_page.PhoneWorker(self.answers, "fixture", safe=True)
        request = urllib.request.Request("http://fixture.invalid/v1/models")
        with mock.patch.object(muse, "_open_no_redirect", return_value="models") as transport:
            self.assertEqual(worker._safe_open(request, timeout=1), "models")
            transport.assert_called_once_with(request, timeout=1)
        self.assertIsNone(request.data)
        self.assertEqual(request.get_method(), "GET")

    def test_safe_pool_retry_inherits_the_safer_opener(self):
        answer = self.answers.ask("m1", "Q")
        with mock.patch.object(ai_page.secrets, "randbits", return_value=303):
            worker = ai_page.PoolWorker(self.answers, answer["id"], None, None, safe=True)
        try:
            self.answers.begin(answer["id"])
            self.job(["safe pool answer"])
            worker._read(_page.ROUTE, "Q")
            self.assertEqual(worker.safe_seed, 303)
            self.assertEqual(muse.stream.call_args.kwargs["opener"], worker._safe_open)
            self.assertEqual(self.answers.latest("m1")["text"], "safe pool answer")
        finally:
            worker._cleanup()

    def test_real_muse_safe_stream_verifies_model_before_sending_completion(self):
        worker = ai_page.PhoneWorker(self.answers, "fixture", safe=True)
        route = muse.Route("fixture", "Fixture", "test", "http://fixture.invalid/v1", "exact", verify_model=True)
        requests = []

        def transport(request, timeout=None):
            requests.append((request.get_method(), request.full_url,
                             None if request.data is None else json.loads(request.data)))
            if request.full_url.endswith("/models"):
                return io.BytesIO(b'{"data":[{"id":"exact"}]}')
            return io.BytesIO(b'data: {"choices":[{"delta":{"content":"safe"},"finish_reason":"stop"}]}\n\n'
                              b'data: [DONE]\n\n')

        with mock.patch.object(muse, "_open_no_redirect", side_effect=transport):
            with muse.stream(route, "Q", opener=worker._safe_open) as stream:
                self.assertEqual(list(stream), ["safe"])
        self.assertEqual(requests[0], ("GET", "http://fixture.invalid/v1/models", None))
        self.assertEqual(requests[1][:2], ("POST", "http://fixture.invalid/v1/chat/completions"))
        self.assertEqual(requests[1][2]["seed"], worker.safe_seed)
        self.assertEqual(requests[1][2]["temperature"], 0.1)
        self.assertEqual(requests[1][2]["repeat_penalty"], 1.1)
        self.assertTrue(requests[1][2]["stream"])
        with mock.patch.object(muse, "_open_no_redirect", return_value=io.BytesIO(b'{"data":[{"id":"wrong"}]}')) as opened:
            with self.assertRaises(muse.MuseError):
                muse.stream(route, "Q", opener=worker._safe_open)
            self.assertEqual(opened.call_count, 1)  # No prompt POST after a wrong model list.

    def test_normal_retry_keeps_the_existing_muse_sampler(self):
        self.job(["first"])
        self.ask()
        self.join_workers()
        old = self.answers.latest("phone")["id"]
        self.job(["ordinary"])
        self.assertEqual(self.retry("phone", old)[0], 200)
        jobs = self.join_workers()
        self.assertIsNone(jobs[0].safe_seed)
        self.assertNotIn("opener", muse.stream.call_args.kwargs)

    def test_safe_retry_on_pc_still_replaces_only_the_requested_lane(self):
        self.pc("g1", "g2")
        self.ask(("g1", "g2"), "Q")
        old = self.answers.latest("g1")["id"]
        sibling = self.answers.latest("g2")["id"]
        self.assertEqual(self.retry("g1", old, safe=1)[0], 200)
        self.assertNotEqual(self.answers.latest("g1")["id"], old)
        self.assertEqual(self.answers.latest("g2")["id"], sibling)

    def test_paused_pc_lane_is_cancelled_through_the_link_and_requeued_on_its_lane_only(self):
        self.pc("g1", "g2")
        status, snap = self.ask(("g1", "g2"), "One question")
        self.assertEqual(status, 200)
        old = {item["pane"]: item["answer"]["id"] for item in snap["models"]}
        self.answers.begin(old["g1"]) if self.answers.get(old["g1"])["state"] == "waiting" else None
        status, snap = self.retry("g1", old["g1"])
        self.assertEqual(status, 200)
        self.assertIn(("cancel", old["g1"]), self.link.calls)
        by_pane = {item["pane"]: item["answer"] for item in snap["models"]}
        self.assertNotEqual(by_pane["g1"]["id"], old["g1"])
        self.assertEqual(by_pane["g1"]["question"], "One question")
        self.assertIn(by_pane["g1"]["state"], ("queued", "waiting"))
        self.assertEqual(by_pane["g2"]["id"], old["g2"])  # the other lane was not touched
        self.assertNotIn(("cancel", old["g2"]), self.link.calls)
        self.assertEqual(self.answers.get(old["g1"])["state"], "cancelled")

    def test_stuck_open_answer_can_be_retried_while_other_lanes_keep_going(self):
        self.pc("g1")
        _, snap = self.ask(("gpu", "g1"), "Long question")
        gpu = self.answers.latest("gpu")
        self.answers.begin(gpu["id"])
        self.answers.append(gpu["id"], 0, b"partial text")
        self.answers.pause(gpu["id"])
        self.assertEqual(self.answers.latest("gpu")["state"], "paused")
        status, snap = self.retry("gpu", gpu["id"])
        self.assertEqual(status, 200)
        fresh = self.answers.latest("gpu")
        self.assertEqual((fresh["question"], fresh["state"], fresh["text"]), ("Long question", fresh["state"], ""))
        self.assertIn(fresh["state"], ("queued", "waiting"))
        self.assertEqual(self.answers.get(gpu["id"])["text"], "partial text")  # kept in history

    def test_a_replayed_or_double_tapped_retry_is_refused_and_changes_nothing(self):
        self.job(["x"], RuntimeError("boom"))
        self.ask()
        self.join_workers()
        old = self.answers.latest("phone")["id"]
        self.job(["y"])
        self.assertEqual(self.retry("phone", old)[0], 200)
        self.join_workers()
        newest = self.answers.latest("phone")["id"]
        self.assertNotEqual(newest, old)
        status, body = self.retry("phone", old)  # the same tap delivered twice
        self.assertEqual(status, 400)
        self.assertIn("replaced", body["error"])
        self.assertEqual(self.answers.latest("phone")["id"], newest)
        self.assertEqual(self.answers.latest("phone")["state"], "done")

    def test_refusals_leave_state_alone(self):
        self.assertEqual(self.retry("phone")[0], 400)            # nothing to retry
        self.assertEqual(self.retry("nope")[0], 400)             # unknown lane
        self.assertEqual(self.retry(None)[0], 400)
        self.pc("g1")
        self.ask(("g1",), "Keep me")
        gpu_like = self.answers.latest("g1")
        self.link.value["pc"]["models"] = []                     # the PC no longer offers g1
        status, body = self.retry("g1", gpu_like["id"])
        self.assertEqual(status, 400)
        # The refused Retry must not have cancelled the answer it could not replace.
        self.assertNotEqual(self.answers.get(gpu_like["id"])["state"], "cancelled")
        self.assertNotIn(("cancel", gpu_like["id"]), self.link.calls)

    def test_retry_without_expected_id_uses_the_latest_answer(self):
        self.job(["a"], RuntimeError("boom"))
        self.ask(question="Q")
        self.join_workers()
        self.job(["b"])
        self.assertEqual(self.retry("phone")[0], 200)
        self.join_workers()
        self.assertEqual(self.answers.latest("phone")["text"], "b")

    def test_retry_never_runs_a_second_answer_on_the_same_lane(self):
        started = threading.Event()
        release = threading.Event()

        def pieces():
            yield "streaming"
            started.set()
            release.wait(3)

        cancels = []

        def open_stream(*args, **kwargs):
            cancels.append(kwargs["cancel"])
            return FakeStream(pieces() if len(cancels) == 1 else ["fresh"])

        from unittest import mock
        with mock.patch.object(muse, "stream", side_effect=open_stream):
            self.ask(question="Q")
            self.assertTrue(started.wait(3))
            old = self.answers.latest("phone")["id"]
            self.assertEqual(self.retry("phone", old)[0], 200)
            release.set()
            self.join_workers()
        self.assertTrue(cancels[0].is_set())
        self.assertEqual(self.answers.get(old)["state"], "cancelled")
        open_phone = [row for row in self.answers.snapshot()["answers"]
                      if row["pane"] == "phone" and row["state"] not in ai_answers.FINAL]
        self.assertEqual(open_phone, [])

    def test_retry_without_an_id_never_cancels_an_open_answer(self):
        started = threading.Event()
        release = threading.Event()

        def pieces():
            yield "streaming"
            started.set()
            release.wait(3)

        from unittest import mock
        with mock.patch.object(muse, "stream", side_effect=lambda *a, **k: FakeStream(pieces())):
            self.ask(question="Q")
            self.assertTrue(started.wait(3))
            old = self.answers.latest("phone")["id"]
            status, body = self.retry("phone")
            self.assertEqual(status, 400)
            self.assertNotEqual(self.answers.get(old)["state"], "cancelled")
            release.set()
            self.join_workers()

    def test_retry_is_accepted_over_the_real_http_endpoint(self):
        self.job(["x"], RuntimeError("boom"))
        self.ask(question="Over the wire")
        self.join_workers()
        old = self.answers.latest("phone")["id"]
        self.job(["wired"])
        with running() as server:
            status, raw = request(server, "/api/ai", {"action": "retry", "pane": "phone", "id": old})
            self.assertEqual(status, 200)
            self.join_workers()
            body = json.loads(raw)
            self.assertNotEqual(body["phone"]["answer"]["id"], old)
            status, raw = request(server, "/api/ai", {"action": "retry", "pane": "phone", "id": old})
            self.assertEqual(status, 400)
            self.assertIn("replaced", json.loads(raw)["error"])
            self.assertEqual(request(server, "/api/ai", {"action": "retry", "pane": "phone"},
                                     token=False)[0], 403)


if __name__ == "__main__":
    unittest.main()

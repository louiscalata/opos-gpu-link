# SPDX-License-Identifier: Apache-2.0
"""A PC lane that never resumed after a replug is rerun by Retry, against the real link service."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from opos import ai_answers, ai_page, apps, assist
from opos.ai_answers import AnswerStore
from opos.gpu_link import LINK_SECONDS, LinkService
from opos.store import Store
from tests.ai_page_support import ROUTE
from tests.gpu_link_fake_pc import Clock, FakePC, RandomBytes


class LaneRetryAgainstTheLink(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.enterContext(mock.patch.dict(os.environ, {
            "OPOS_STATE_DIR": self.temp.name, "OPOS_APPS": "ai",
            "OPOS_MODEL_POOL": str(root / "missing-pool.json")}))
        self.store = Store(root / "state")
        self.answers = AnswerStore(self.store)
        self.clock, self.rand = Clock(), RandomBytes()
        model = root / "model.gguf"
        model.write_bytes(b"model bytes\x00\xff" * 16)
        self.link = LinkService(self.answers, self.store, model, clock=self.clock, rand=self.rand)
        self.addCleanup(self.link.close)
        if self.link._hasher:
            self.link._hasher.join(2)
        self.pc = FakePC(self.link)
        self.enterContext(mock.patch.object(ai_answers, "shared", return_value=self.answers))
        self.state = ai_page.PageState()
        self.enterContext(mock.patch.object(ai_page, "_STATE", self.state))
        self.enterContext(mock.patch.object(assist, "free_mb", return_value=2048))
        self.enterContext(mock.patch.object(assist, "local_route", return_value=ROUTE))
        self.enterContext(mock.patch.object(ai_page, "gpu_link_server",
                                            SimpleNamespace(service=lambda: self.link)))
        apps.register(ai_page.APP)
        self.addCleanup(self.state.close)
        assert self.pc.enrol().status == 202 and self.link.allow(self.pc.code)
        assert self.pc.hello().status == 200
        models = [{"id": f"vendor/model-{n}", "label": f"Model {n}", "maker": "Maker", "gpu": None}
                  for n in (1, 2)]
        self.assertEqual(self.pc.data(self.pc.advertise(models)), {"accepted": 2})

    def ready(self):
        self.assertEqual(self.pc.status("ready").status, 200)
        for pane in ("g1", "g2"):
            self.assertEqual(self.pc.lane_status(pane, "ready").status, 200)

    def test_lane_that_never_resumes_is_rerun_by_retry_and_finishes(self):
        self.ready()
        status, _ = ai_page.post({"action": "ask", "question": "How does a pc work",
                                  "panes": ["gpu", "g1", "g2"]})
        self.assertEqual(status, 200)
        rows = {p: self.answers.latest(p) for p in ("gpu", "g1", "g2")}
        jobs = {"gpu": self.pc.data(self.pc.work()),
                "g1": self.pc.data(self.pc.lane_work("g1")),
                "g2": self.pc.data(self.pc.lane_work("g2"))}
        for pane, text in (("gpu", "lead "), ("g1", "one "), ("g2", "two ")):
            self.assertEqual(self.pc.text(jobs[pane]["lease"], 0, text).status, 200)
        # The cable is pulled: every PC lane pauses with its text kept.
        self.clock.advance(LINK_SECONDS)
        self.link.tick()
        for pane in rows:
            self.assertEqual(self.answers.get(rows[pane]["id"])["state"], "paused")
        # The cable is back. gpu and g1 resume; g2's worker never polls again (the bug in the field).
        self.clock.advance(1)
        self.ready()
        resumed = {"gpu": self.pc.data(self.pc.work()), "g1": self.pc.data(self.pc.lane_work("g1"))}
        self.assertEqual(self.pc.data(self.pc.text(resumed["gpu"]["lease"], 5, "done", True, "stop")),
                         {"acked": 9})
        self.assertEqual(self.pc.data(self.pc.text(resumed["g1"]["lease"], 4, "done", True, "stop")),
                         {"acked": 8})
        self.assertEqual(self.answers.get(rows["g2"]["id"])["state"], "paused")
        # The user taps Retry on g2.
        status, snap = ai_page.post({"action": "retry", "pane": "g2", "id": rows["g2"]["id"]})
        self.assertEqual(status, 200)
        by_pane = {item["pane"]: item["answer"] for item in snap["models"]}
        self.assertNotEqual(by_pane["g2"]["id"], rows["g2"]["id"])
        self.assertEqual(by_pane["g2"]["question"], "How does a pc work")
        self.assertEqual(self.answers.get(rows["g2"]["id"])["state"], "cancelled")
        # The dead lease cannot write into the new answer.
        self.assertEqual(self.pc.text(jobs["g2"]["lease"], 4, "late").status, 404)
        # The PC's lane worker polls and gets the same question from the start.
        again = self.pc.data(self.pc.lane_work("g2"))
        self.assertEqual(again["question"], "How does a pc work")
        self.assertEqual(again.get("partial", ""), "")
        self.assertEqual(self.pc.text(again["lease"], 0, "fresh answer", True, "stop").status, 200)
        final = self.answers.latest("g2")
        self.assertEqual((final["state"], final["text"]), ("done", "fresh answer"))
        # The lanes that had resumed were not touched.
        self.assertEqual(self.answers.get(rows["gpu"]["id"])["text"], "lead done")
        self.assertEqual(self.answers.get(rows["g1"]["id"])["text"], "one done")

    def test_retry_while_the_cable_is_still_out_waits_for_the_pc_then_runs(self):
        self.ready()
        ai_page.post({"action": "ask", "question": "Q", "panes": ["g1"]})
        row = self.answers.latest("g1")
        job = self.pc.data(self.pc.lane_work("g1"))
        self.pc.text(job["lease"], 0, "part ")
        self.clock.advance(LINK_SECONDS)
        self.link.tick()
        self.assertEqual(self.answers.get(row["id"])["state"], "paused")
        status, _ = ai_page.post({"action": "retry", "pane": "g1", "id": row["id"]})
        self.assertEqual(status, 200)
        fresh = self.answers.latest("g1")
        self.assertIn(fresh["state"], ("queued", "waiting"))
        self.clock.advance(1)
        self.ready()
        again = self.pc.data(self.pc.lane_work("g1"))
        self.assertEqual(again["question"], "Q")
        self.assertEqual(again.get("partial", ""), "")


if __name__ == "__main__":
    unittest.main()

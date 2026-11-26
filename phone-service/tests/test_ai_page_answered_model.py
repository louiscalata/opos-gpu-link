# SPDX-License-Identifier: Apache-2.0
"""A phone pool lane's answer keeps the model that wrote it after the pool changes.

The lane's label/model describe the slot (lane choice and hiding key on them); the card names a
shown answer by answer["model"]."""

import unittest
from pathlib import Path
from unittest import mock

try:
    from opos import ai_model_pool, ai_page
    from tests import test_ai_page as _page
except ImportError as missing:  # the repo copy has no host app
    _page = None
    _missing = missing


@unittest.skipIf(_page is None, "needs the host app (ai_model_pool)")
class AnsweredModel(unittest.TestCase):
    if _page is not None:
        setUp = _page.AiPage.setUp
        close_workers = _page.AiPage.close_workers
        job = _page.AiPage.job
        join_workers = _page.AiPage.join_workers

    def slot(self, label, maker):
        return ai_model_pool.Model(pane="m1", label=label, maker=maker, path=Path("/missing.gguf"),
                                   ctx=512, max_tokens=64, threads=1, file_mb=1)

    def test_finished_answer_keeps_its_model_after_the_slot_changes(self):
        answer = self.answers.ask("m1", "Earlier question", model="Qwen2.5 1.5B")
        self.answers.begin(answer["id"])
        self.answers.append(answer["id"], 0, b"Done.", done=True, finish="stop")
        with mock.patch.object(ai_model_pool, "models", return_value=(self.slot("Nemotron 3 Nano 4B", "NVIDIA"),)):
            lane = {item["pane"]: item for item in ai_page.snapshot()["models"]}["m1"]
        self.assertEqual(lane["label"], "Nemotron 3 Nano 4B")  # the slot, for choosing lanes
        self.assertEqual(lane["model"], "Nemotron 3 Nano 4B")  # the slot, for hiding and details
        self.assertEqual(lane["answer"]["model"], "Qwen2.5 1.5B")  # the answer, for its card

    def test_a_new_answer_records_the_slot_model_it_runs_on(self):
        with mock.patch.object(ai_model_pool, "models", return_value=(self.slot("Nemotron 3 Nano 4B", "NVIDIA"),)):
            answer = self.answers.ask("m1", "New question", model="Nemotron 3 Nano 4B")
            lane = {item["pane"]: item for item in ai_page.snapshot()["models"]}["m1"]
        self.assertEqual(lane["answer"]["id"], answer["id"])
        self.assertEqual(lane["answer"]["model"], "Nemotron 3 Nano 4B")

    def test_empty_lane_is_named_by_its_slot(self):
        with mock.patch.object(ai_model_pool, "models", return_value=(self.slot("Nemotron 3 Nano 4B", "NVIDIA"),)):
            lane = {item["pane"]: item for item in ai_page.snapshot()["models"]}["m1"]
        self.assertEqual(lane["model"], "Nemotron 3 Nano 4B")
        self.assertIsNone(lane["answer"])


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""The service stamps a lane's wall-clock finish once; no network, no models."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from opos import ai_answers
from opos.store import Store


class EndedStamp(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.answers = ai_answers.AnswerStore(Store(self.root))

    def tearDown(self):
        self.temp.cleanup()

    def _start(self, pane="gpu"):
        row = self.answers.ask(pane, "Explain how a monitor works.", "Gemma 4 26B")
        return self.answers.begin(row["id"])

    def test_open_answers_have_no_stamp(self):
        row = self._start()
        self.assertNotIn("ended_ms", self.answers.get(row["id"]))
        self.answers.append(row["id"], 0, b"A monitor shows", done=False)
        self.assertNotIn("ended_ms", self.answers.get(row["id"]))

    def test_done_is_stamped_once_and_survives_replay_and_reload(self):
        row = self._start()
        text = b"A monitor shows pictures."
        with mock.patch.object(ai_answers.time, "time", return_value=1_795_724_000.25):
            self.answers.append(row["id"], 0, text, done=True, finish="stop")
        first = self.answers.get(row["id"])["ended_ms"]
        self.assertEqual(first, 1_795_724_000_250)
        with mock.patch.object(ai_answers.time, "time", return_value=1_795_724_099.0):
            self.answers.append(row["id"], 0, text, done=True, finish="stop")
        self.assertEqual(self.answers.get(row["id"])["ended_ms"], first)
        reloaded = ai_answers.AnswerStore(Store(self.root))
        self.assertEqual(reloaded.get(row["id"])["ended_ms"], first)
        self.assertFalse(any(".bad-" in path.name for path in self.root.iterdir()))

    def test_cancelled_is_stamped(self):
        row = self._start("phone")
        before = int(time.time() * 1000)
        self.answers.cancel(row["id"])
        shown = self.answers.get(row["id"])
        self.assertEqual(shown["state"], "cancelled")
        self.assertGreaterEqual(shown["ended_ms"], before)


if __name__ == "__main__":
    unittest.main()

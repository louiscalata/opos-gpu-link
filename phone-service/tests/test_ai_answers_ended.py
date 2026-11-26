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

    def test_failed_is_stamped(self):
        row = self._start("phone")
        with mock.patch.object(ai_answers.time, "time", return_value=1_795_724_010.0):
            self.answers.fail(row["id"], "restart")
        self.assertEqual(self.answers.get(row["id"])["ended_ms"], 1_795_724_010_000)

    def test_later_saves_keep_the_first_stamp(self):
        row = self._start()
        with mock.patch.object(ai_answers.time, "time", return_value=1_795_724_000.0):
            self.answers.append(row["id"], 0, b"A monitor shows pictures.", done=True, finish="stop")
        with mock.patch.object(ai_answers.time, "time", return_value=1_795_724_500.0):
            self.answers.note(row["id"], tokens=5, tps=12.5)
        shown = self.answers.get(row["id"])
        self.assertEqual(shown["tokens"], 5)
        self.assertEqual(shown["ended_ms"], 1_795_724_000_000)

    def _rewrite(self, ident, **changes):
        import json
        path = self.root / f"ai-answer-{ident}.json"
        record = json.loads(path.read_text())
        for key, value in changes.items():
            if value is None:
                record["answer"].pop(key, None)
            else:
                record["answer"][key] = value
        path.write_text(json.dumps(record))

    def test_older_final_record_is_not_stamped_later(self):
        row = self._start()
        self.answers.append(row["id"], 0, b"A monitor shows pictures.", done=True, finish="stop")
        self._rewrite(row["id"], ended_ms=None)
        reloaded = ai_answers.AnswerStore(Store(self.root))
        reloaded.note(row["id"], tokens=5)
        self.assertNotIn("ended_ms", reloaded.get(row["id"]))

    def test_bad_stamps_on_disk_are_dropped_not_trusted(self):
        done = self._start()
        self.answers.append(done["id"], 0, b"A monitor shows pictures.", done=True, finish="stop")
        self._rewrite(done["id"], ended_ms="soon")
        reloaded = ai_answers.AnswerStore(Store(self.root))
        shown = reloaded.get(done["id"])
        self.assertEqual(shown["state"], "done")
        self.assertNotIn("ended_ms", shown)

    def test_stamp_on_an_open_record_is_dropped(self):
        row = self._start("m1")
        self.answers.append(row["id"], 0, b"A monitor", done=False)
        self._rewrite(row["id"], ended_ms=1)
        reloaded = ai_answers.AnswerStore(Store(self.root))
        self.assertNotIn("ended_ms", reloaded.get(row["id"]))


if __name__ == "__main__":
    unittest.main()

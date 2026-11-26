# SPDX-License-Identifier: Apache-2.0
"""Length-cap sentence trimming; no network, no models."""

import tempfile
import unittest
from pathlib import Path

from opos import ai_answers
from opos.store import Store


class CompleteSentences(unittest.TestCase):
    def test_trims_a_hanging_clause_after_the_last_period(self):
        text = (
            "A GPU is a specialized processor designed for parallel work. "
            "2. Rasterization: Converting those 3D vector shapes into a"
        )
        self.assertEqual(
            ai_answers.complete_sentences(text),
            "A GPU is a specialized processor designed for parallel work.",
        )

    def test_keeps_a_complete_ending(self):
        text = "A GPU is a specialized processor. It has many cores."
        self.assertEqual(ai_answers.complete_sentences(text), text)

    def test_keeps_text_when_there_is_no_sentence_end(self):
        text = "A hanging clause with no terminator"
        self.assertEqual(ai_answers.complete_sentences(text), text)

    def test_does_not_treat_list_numbers_as_sentence_ends(self):
        text = "A GPU has two steps. 2. Rasterization converts shapes into pixels."
        self.assertEqual(ai_answers.complete_sentences(text), text)


class LengthCapAppend(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.answers = ai_answers.AnswerStore(Store(Path(self.temp.name)))

    def tearDown(self):
        self.temp.cleanup()

    def _start(self):
        row = self.answers.ask("gpu", "Explain how a gpu works in detail?", "Gemma 4 26B")
        return self.answers.begin(row["id"])

    def test_length_finish_trims_only_when_done(self):
        row = self._start()
        hanging = (
            "A GPU is a specialized processor designed for parallel work. "
            "Converting those 3D vector shapes into a"
        )
        mid = self.answers.append(row["id"], 0, hanging.encode(), done=False)
        self.assertEqual(mid["text"], hanging)
        done = self.answers.append(row["id"], len(hanging.encode()), b"", done=True, finish="length")
        self.assertEqual(done["state"], "done")
        self.assertEqual(done["finish"], "length")
        self.assertEqual(done["text"], "A GPU is a specialized processor designed for parallel work.")

    def test_stop_finish_is_not_trimmed(self):
        row = self._start()
        text = "A GPU is a specialized processor designed for parallel work. And then"
        done = self.answers.append(row["id"], 0, text.encode(), done=True, finish="stop")
        self.assertEqual(done["text"], text)

    def test_length_replay_after_trim_is_accepted(self):
        row = self._start()
        text = "A GPU is a specialized processor designed for parallel work. And then"
        self.answers.append(row["id"], 0, text.encode(), done=True, finish="length")
        again = self.answers.append(row["id"], 0, text.encode(), done=True, finish="length")
        self.assertEqual(again["finish"], "length")
        self.assertTrue(again["text"].endswith("work."))


if __name__ == "__main__":
    unittest.main()

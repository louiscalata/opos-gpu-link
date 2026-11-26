"""Grounded lane instructions with in-memory HTTP only; no socket or model."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import gpu_link_worker as worker
from test_gpu_link_guard_stream import FakeHTTP, answer, job


class SystemPromptTests(unittest.TestCase):
    def test_default_uses_the_shared_prompt_and_does_not_mutate_messages(self):
        messages = [{"role": "user", "content": "A question"}]
        expected = Path(__file__).with_name("demo_system_prompt.txt").read_text(encoding="utf-8").strip()
        with patch.dict(os.environ, {worker.SYSTEM_PROMPT_ENV: "1"}):
            result = worker.default_system_message(messages)
        self.assertEqual(result, [{"role": "system", "content": expected}, *messages])
        self.assertEqual(messages, [{"role": "user", "content": "A question"}])

    def test_existing_system_message_is_preserved_without_reading_default(self):
        messages = [{"role": "system", "content": "Use the supplied instruction."},
                    {"role": "user", "content": "A question"}]
        with patch.dict(os.environ, {worker.SYSTEM_PROMPT_ENV: "1"}), \
                patch.object(Path, "read_text", side_effect=AssertionError("unneeded resource read")):
            self.assertIs(worker.default_system_message(messages), messages)

    def test_disable_switch_leaves_messages_unchanged_without_reading_file(self):
        messages = [{"role": "user", "content": "A question"}]
        with patch.dict(os.environ, {worker.SYSTEM_PROMPT_ENV: "0"}), \
                patch.object(Path, "read_text", side_effect=AssertionError("disabled resource read")):
            self.assertIs(worker.default_system_message(messages), messages)

    def test_missing_or_empty_prompt_fails_with_a_safe_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            prompt = Path(directory) / "prompt.txt"
            with patch.dict(os.environ, {worker.SYSTEM_PROMPT_ENV: "1"}), \
                    patch.object(worker, "SYSTEM_PROMPT_PATH", prompt):
                with self.assertRaisesRegex(worker.ToolError, "prompt is unavailable"):
                    worker.default_system_message([])
                prompt.write_text(" \n", encoding="utf-8")
                with self.assertRaisesRegex(worker.ToolError, "prompt is empty"):
                    worker.default_system_message([])

    def test_actual_stream_keeps_phone_question_and_resume_prefix(self):
        fake = FakeHTTP(lambda _body, _index: answer("Complete answer."))
        original_job = job(partial="A saved prefix. ")
        original_copy = dict(original_job)
        with patch.dict(os.environ, {worker.SYSTEM_PROMPT_ENV: "1", "OPOS_GPU_LINK_GUARD": "0"}), \
                patch.object(worker.http.client, "HTTPConnection", fake):
            source = worker.ServerSource(original_job, "http://127.0.0.1:38101/v1/chat/completions", "model")
            try:
                source.worker.join(3)
                self.assertFalse(source.worker.is_alive())
                self.assertFalse(source.snapshot()[-1])
            finally:
                source.close()
        self.assertEqual(original_job, original_copy)
        messages = fake.requests[0]["messages"]
        self.assertEqual([message["role"] for message in messages], ["system", "user", "assistant"])
        self.assertEqual(messages[1]["content"], original_job["question"])
        self.assertEqual(messages[2]["content"], original_job["partial"])

    def test_disabled_stream_sends_the_existing_user_only_request(self):
        fake = FakeHTTP(lambda _body, _index: answer("Complete answer."))
        with patch.dict(os.environ, {worker.SYSTEM_PROMPT_ENV: "0", "OPOS_GPU_LINK_GUARD": "0"}), \
                patch.object(worker.http.client, "HTTPConnection", fake):
            source = worker.ServerSource(job(), "http://127.0.0.1:38101/v1/chat/completions", "model")
            try:
                source.worker.join(3)
                self.assertFalse(source.worker.is_alive())
                self.assertFalse(source.snapshot()[-1])
            finally:
                source.close()
        self.assertEqual(fake.requests[0]["messages"], [{"role": "user", "content": job()["question"]}])


if __name__ == "__main__":
    unittest.main()

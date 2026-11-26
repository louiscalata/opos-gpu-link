# SPDX-License-Identifier: Apache-2.0
"""Deterministic validator checks; HTTP tests use only our own 383xx server."""
from __future__ import annotations

import contextlib
import errno
import io
import json
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request

import gpu_link_validate as v


def prompt(**changes):
    item = {
        "id": "capital", "text": "What is the capital of Australia?",
        "max_tokens": 64, "expected_facts": [[r"\bCanberra\b"]],
        "forbidden_patterns": [r"\ASydney\.?\Z"], "kind": "fact",
        "note": "A small deterministic fixture.",
    }
    item.update(changes)
    return item


class AnswerChecks(unittest.TestCase):
    def test_expected_groups_require_every_group_but_allow_alternatives(self):
        item = prompt(expected_facts=[[r"eight", r"\b8\b"], [r"bits?"]],
                      forbidden_patterns=[])
        self.assertEqual(v.check_answer(item, "8 BITS.")["verdict"], "PASS")
        self.assertEqual(v.check_answer(item, "Eight bits.")["verdict"], "PASS")
        self.assertEqual(v.check_answer(item, "Eight bytes.")["verdict"], "FAIL")
        self.assertEqual(v.check_answer(item, "Some bits.")["verdict"], "FAIL")

    def test_wrong_capital_fails_and_correct_capital_passes(self):
        self.assertEqual(v.check_answer(prompt(), "Canberra.")["verdict"], "PASS")
        wrong = v.check_answer(prompt(), "Sydney.")
        self.assertEqual(wrong["verdict"], "FAIL")
        self.assertTrue(wrong["failures"])

    def test_forbidden_patterns_are_checked_even_when_expected_fact_matches(self):
        item = prompt(forbidden_patterns=[r"definitely\s+Sydney"])
        result = v.check_answer(item, "Canberra? The answer is definitely Sydney.")
        self.assertEqual(result["verdict"], "FAIL")
        self.assertTrue(result["failures"])

    def test_a_negated_wrong_city_can_be_allowed_by_curated_pattern(self):
        item = prompt(forbidden_patterns=[r"\A(?![\s\S]*\bCanberra\b)[\s\S]*\bSydney\b"])
        self.assertEqual(v.check_answer(item, "Canberra, not Sydney.")["verdict"], "PASS")

    def test_trap_requires_uncertainty_even_without_expected_fact_group(self):
        item = prompt(kind="trap", expected_facts=[], forbidden_patterns=[])
        self.assertEqual(v.check_answer(item, "Argentina won the tournament.")["verdict"], "FAIL")
        for answer in ("I'm not sure.", "Not sure.", "I don't know.", "I cannot know that yet.",
                       "No information is available to me."):
            with self.subTest(answer=answer):
                self.assertEqual(v.check_answer(item, answer)["verdict"], "PASS")

    def test_curated_trap_rejects_hedge_followed_by_invented_winner(self):
        item = next(p for p in v.load_prompts() if p["id"] == "future_world_cup")
        for answer in ("I'm not sure. Brazil won the 2031 FIFA Women's World Cup.",
                       "I'm not sure, but the winner was Brazil.",
                       "I'm not sure, Atlantis won it."):
            with self.subTest(answer=answer):
                self.assertEqual(v.check_answer(item, answer)["verdict"], "FAIL")
        for answer in ("I'm not sure.", "I'm not sure. The event has not happened yet."):
            self.assertEqual(v.check_answer(item, answer)["verdict"], "PASS")

    def test_known_rx580_garbage_fails_even_after_readable_answer(self):
        item = prompt(expected_facts=[], forbidden_patterns=[], max_chars=12000)
        prose = "A GPU transforms vertices into triangles, then shades the pixels. "
        fixtures = [prose * 45 + "-@" + "@" * 3551,
                    "8" * 200, "asks8alion" * 120,
                    prose + "asks8alion" * 8]
        for answer in fixtures:
            with self.subTest(length=len(answer), tail=answer[-20:]):
                result = v.check_answer(item, answer)
                self.assertEqual(result["verdict"], "FAIL")
                self.assertTrue(result["garble_reason"])

    def test_known_good_text_is_not_garbage(self):
        item = prompt(expected_facts=[], forbidden_patterns=[])
        fixtures = [
            "The GPU shades pixels and writes an image to a frame buffer.",
            "-" * 80, "|---" * 9,
            "```python\nprint('hello')\n```",
            "1. Transform vertices.\n2. Rasterize triangles.\n3. Shade pixels.",
            "ha ha ha ha", "Una GPU procesa los píxeles de una imagen.",
            "图形处理器并行处理像素，生成图像。", "GPUは並列に画素を処理します。",
            "17 × 23 = 391", "def reverse(s):\n    return s[::-1]",
        ]
        for answer in fixtures:
            with self.subTest(answer=answer):
                result = v.check_answer(item, answer)
                self.assertIsNone(result["garble_reason"])
                self.assertNotEqual(result["verdict"], "FAIL")

    def test_empty_and_prompt_length_limits_do_not_pass(self):
        item = prompt(expected_facts=[], forbidden_patterns=[])
        self.assertEqual(v.check_answer(item, "   \n")["verdict"], "FAIL")
        result = v.check_answer(prompt(expected_facts=[], forbidden_patterns=[], min_chars=30), "Brief.")
        self.assertNotEqual(result["verdict"], "PASS")
        result = v.check_answer(prompt(max_chars=10), "Canberra is Australia's capital.")
        self.assertNotEqual(result["verdict"], "PASS")

    def test_leaked_thinking_tag_warns_but_does_not_fail(self):
        result = v.check_answer(prompt(), "Canberra.</think>Canberra.")
        self.assertEqual(result["verdict"], "WARN")
        self.assertTrue(any("leaked" in w for w in result["warnings"]))

    def test_truncation_is_visible(self):
        result = v.check_answer(prompt(), "Canberra.", finish_reason="length")
        self.assertNotEqual(result["verdict"], "PASS")
        self.assertTrue(result["warnings"] or result["failures"])

    def test_system_prompt_and_curated_schema(self):
        self.assertGreater(len(v.SYSTEM_PROMPT.split()), 0)
        self.assertLess(len(v.SYSTEM_PROMPT.split()), 80)
        text = Path(__file__).with_name("demo_system_prompt.txt").read_text("utf-8").strip()
        self.assertEqual(v.SYSTEM_PROMPT.strip(), text)
        prompts = v.load_prompts()
        self.assertEqual(len(prompts), 12)
        self.assertEqual(len({p["id"] for p in prompts}), len(prompts))
        self.assertTrue({"fact", "howto", "trap", "long"}.issubset({p["kind"] for p in prompts}))
        for item in prompts:
            self.assertTrue({"id", "text", "max_tokens", "expected_facts", "forbidden_patterns",
                             "kind", "note"}.issubset(item))
            self.assertGreater(item["max_tokens"], 0)
            self.assertIsInstance(item["expected_facts"], list)


class FakeOpenAI:
    """Binds only a free C-lane port and closes its own listener on exit."""
    def __init__(self):
        self.requests = []
        self.reply = "Canberra."
        self.status = 200
        self.raw_body = None
        self.usage = {"completion_tokens": 4, "prompt_tokens": 20, "total_tokens": 24}

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                owner.requests.append({"path": self.path, "body": json.loads(raw),
                                       "auth": self.headers.get("Authorization")})
                body = owner.raw_body
                if body is None:
                    request = owner.requests[-1]["body"]
                    body = json.dumps({
                        "model": request["model"],
                        "choices": [{"message": {"content": owner.reply}, "finish_reason": "stop"}],
                        "usage": owner.usage,
                    }).encode("utf-8")
                self.send_response(owner.status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        for port in range(38300, 38400):
            try:
                self.server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
                break
            except OSError as error:
                if error.errno != errno.EADDRINUSE:
                    raise
        else:
            raise RuntimeError("No free C-lane fake-server port in 38300-38399")
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": 0.01}, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)


class OpenAIIntegration(unittest.TestCase):
    def setUp(self):
        self.fake_context = FakeOpenAI()
        try:
            self.fake = self.fake_context.__enter__()
        except OSError as error:
            if error.errno in (errno.EPERM, errno.EACCES):
                self.skipTest("sandbox denies binding our 383xx fake server")
            raise
        self.addCleanup(self.fake_context.__exit__, None, None, None)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.report = Path(self.tmp.name) / "report.json"
        self.md = Path(self.tmp.name) / "report.md"

    def run_cli(self, *args, prompts=None):
        output = io.StringIO()
        with patch.object(v, "load_prompts", return_value=prompts or [prompt()]), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            code = v.main(["--server", self.fake.url, "--model", "fixture-model",
                           "--report", str(self.report), "--md", str(self.md), *args])
        report = json.loads(self.report.read_text("utf-8")) if self.report.exists() else None
        return code, output.getvalue(), report

    def test_good_answer_report_table_and_actual_system_message(self):
        code, output, report = self.run_cli()
        self.assertEqual(code, 0, output)
        self.assertEqual(report["schema_version"], 1)
        self.assertEqual(report["verdict"], "PASS")
        self.assertIn("checks", report["meaning"].lower())
        self.assertEqual(report["system_prompt"], "demo")
        self.assertEqual(report["phone"]["status"], "NOT_RUN")
        self.assertIn("fixture-model", output)
        self.assertIn("capital", output)
        self.assertIn("PASS", self.md.read_text("utf-8"))
        self.assertEqual(self.fake.requests[0]["path"], "/v1/chat/completions")
        body = self.fake.requests[0]["body"]
        self.assertEqual(body["model"], "fixture-model")
        self.assertEqual(body["max_tokens"], 64)
        self.assertFalse(body.get("stream", False))
        self.assertEqual(body["messages"][0], {"role": "system", "content": v.SYSTEM_PROMPT})
        self.assertEqual(body["messages"][-1], {"role": "user", "content": prompt()["text"]})
        model = report["models"][0]
        self.assertEqual(model["model"], "fixture-model")
        self.assertEqual(model["verdict"], "PASS")
        row = model["results"][0]
        self.assertEqual(row["prompt_id"], "capital")
        self.assertEqual(row["completion_tokens"], 4)
        self.assertGreater(row["latency_seconds"], 0)
        self.assertGreater(row["tokens_per_second"], 0)
        self.assertEqual(row["reported_model"], "fixture-model")
        self.assertEqual(row["finish_reason"], "stop")

    def test_none_system_prompt_sends_only_user_message(self):
        code, output, report = self.run_cli("--system-prompt", "none")
        self.assertEqual(code, 0, output)
        self.assertEqual(report["system_prompt"], "none")
        self.assertEqual([m["role"] for m in self.fake.requests[0]["body"]["messages"]], ["user"])

    def test_auth_file_is_used_but_not_written_in_report_or_printed(self):
        key = Path(self.tmp.name) / "fixture-key"
        key.write_text("validator-test-credential\n", encoding="utf-8")
        code, output, report = self.run_cli("--api-key-file", str(key))
        self.assertEqual(code, 0, output)
        self.assertEqual(self.fake.requests[0]["auth"], "Bearer validator-test-credential")
        for text in (output, json.dumps(report), self.md.read_text("utf-8")):
            self.assertNotIn("validator-test-credential", text)

    def test_wrong_answer_and_garbage_exit_nonzero_with_flags(self):
        for answer in ("Sydney.", "@" * 200):
            with self.subTest(answer=answer[:20]):
                self.fake.reply = answer
                code, output, report = self.run_cli()
                self.assertEqual(code, 1, output)
                self.assertEqual(report["verdict"], "FAIL")
                self.assertIn("FLAG: fixture-model capital", output)

    def test_trap_confidence_fails_and_uncertainty_passes_over_http(self):
        item = prompt(id="future", kind="trap", expected_facts=[], forbidden_patterns=[])
        self.fake.reply = "Brazil won it."
        code, output, _ = self.run_cli(prompts=[item])
        self.assertEqual(code, 1, output)
        self.fake.reply = "I'm not sure."
        code, output, report = self.run_cli(prompts=[item])
        self.assertEqual(code, 0, output)
        self.assertEqual(report["verdict"], "PASS")

    def test_runs_and_additional_models_have_separate_result_rows(self):
        code, output, report = self.run_cli("--models", "model-two,model-three", "--runs", "2")
        self.assertEqual(code, 0, output)
        self.assertEqual([m["model"] for m in report["models"]],
                         ["fixture-model", "model-two", "model-three"])
        self.assertEqual([len(m["results"]) for m in report["models"]], [2, 2, 2])
        self.assertEqual(len(self.fake.requests), 6)
        self.assertEqual(len({r["run"] for r in report["models"][0]["results"]}), 2)

    def test_missing_usage_remains_unknown(self):
        self.fake.usage = {}
        code, output, report = self.run_cli()
        self.assertEqual(code, 0, output)
        row = report["models"][0]["results"][0]
        self.assertIsNone(row["completion_tokens"])
        self.assertIsNone(row["tokens_per_second"])

    def test_http_error_and_invalid_json_fail_without_raw_body(self):
        for status, body in ((503, b"server-private-error"), (200, b"not-json")):
            with self.subTest(status=status):
                self.fake.status, self.fake.raw_body = status, body
                code, output, report = self.run_cli()
                self.assertEqual(code, 1, output)
                self.assertEqual(report["verdict"], "FAIL")
                self.assertNotIn("server-private-error", output)
                self.assertNotIn("server-private-error", json.dumps(report))

    def test_phone_without_endpoint_is_explicitly_not_run(self):
        code, output, report = self.run_cli("--phone")
        self.assertEqual(code, 0, output)
        self.assertIn("phone: NOT_RUN", output)
        self.assertEqual(report["phone"]["status"], "NOT_RUN")


class MockedTransport(unittest.TestCase):
    """Exercise transport parsing without sockets; not evidence of native HTTP."""
    def answer(self, text="Canberra.", **changes):
        value = {"answer": text, "latency_seconds": 0.2, "completion_tokens": 4,
                 "tokens_per_second": 20.0, "reported_model": "fixture-model",
                 "finish_reason": "stop"}
        value.update(changes)
        return value

    def payload(self):
        return {"model": "fixture-model", "choices": [{"message": {"content": "Canberra."},
                "finish_reason": "stop"}], "usage": {"completion_tokens": 4}}

    def request(self, raw=None, error=None):
        opener = MagicMock()
        if error is not None:
            opener.open.side_effect = error
        else:
            response = io.BytesIO(raw if raw is not None else json.dumps(self.payload()).encode())
            opener.open.return_value = response
        with patch.object(v, "build_opener", return_value=opener), \
                patch.object(v.time, "monotonic", side_effect=[10.0, 10.2]):
            result = v.request_answer("http://127.0.0.1:38375/v1/chat/completions", "fixture-model",
                                      prompt(), v.SYSTEM_PROMPT, "test-only-key", 2.5)
        return result, opener

    def test_request_encoding_system_message_auth_and_metrics_without_socket(self):
        result, opener = self.request()
        request = opener.open.call_args.args[0]
        self.assertIsInstance(request, Request)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "http://127.0.0.1:38375/v1/chat/completions")
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 2.5)
        self.assertEqual(request.get_header("Authorization"), "Bearer test-only-key")
        body = json.loads(request.data)
        self.assertEqual(body["messages"], [{"role": "system", "content": v.SYSTEM_PROMPT},
                                            {"role": "user", "content": prompt()["text"]}])
        self.assertEqual(body["model"], "fixture-model")
        self.assertEqual(body["max_tokens"], 64)
        self.assertFalse(body["stream"])
        self.assertEqual(result["answer"], "Canberra.")
        self.assertEqual(result["reported_model"], "fixture-model")
        self.assertEqual(result["finish_reason"], "stop")
        self.assertEqual(result["completion_tokens"], 4)
        self.assertEqual(result["latency_seconds"], 0.2)
        self.assertEqual(result["tokens_per_second"], 20.0)

    def test_request_turns_hidden_thinking_off_like_the_lanes(self):
        _, opener = self.request()
        body = json.loads(opener.open.call_args.args[0].data)
        self.assertEqual(body["reasoning_effort"], "none")
        self.assertEqual(body["chat_template_kwargs"], {"enable_thinking": False})

    def test_reasoning_only_reply_is_flagged(self):
        payload = {"model": "fixture-model", "choices": [{"message": {"content": "", "reasoning_content": "thinking..."},
                   "finish_reason": "length"}], "usage": {"completion_tokens": 64}}
        result, _ = self.request(raw=json.dumps(payload).encode())
        self.assertTrue(result["reasoning_only"])
        self.assertEqual(result["answer"], "")

    def test_missing_usage_is_unknown_and_nontext_response_is_rejected(self):
        payload = self.payload()
        del payload["usage"]
        result, _ = self.request(json.dumps(payload).encode())
        self.assertIsNone(result["completion_tokens"])
        self.assertIsNone(result["tokens_per_second"])
        payload["choices"][0]["message"]["content"] = None
        with self.assertRaises(v.ValidationError):
            self.request(json.dumps(payload).encode())

    def test_malformed_usage_is_a_bounded_validation_failure(self):
        for usage in ([1], True, 4, "not-a-mapping"):
            with self.subTest(usage=usage):
                payload = self.payload()
                payload["usage"] = usage
                with self.assertRaises(v.ValidationError):
                    self.request(json.dumps(payload).encode())

    def test_bad_http_json_and_unreachable_errors_are_bounded(self):
        error = HTTPError("http://127.0.0.1:38375", 503, "private server error", {},
                          io.BytesIO(b"private-response"))
        for raw, exc in ((None, error), (b"not-json", None), (b"{}", None),
                         (None, URLError("private connection detail"))):
            with self.subTest(raw=raw, error=type(exc).__name__):
                with self.assertRaises(v.ValidationError) as raised:
                    self.request(raw, exc)
                self.assertNotIn("private", str(raised.exception))

    def test_truncated_http_response_writes_failed_report_without_traceback(self):
        from http.client import IncompleteRead
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value.read.side_effect = IncompleteRead(b"private", 100)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "truncated.json"
            with patch.object(v, "load_prompts", return_value=[prompt()]), \
                    patch.object(v, "build_opener", return_value=opener), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                code = v.main(["--server", "http://127.0.0.1:38375", "--model", "fixture-model",
                               "--report", str(path)])
            report = json.loads(path.read_text("utf-8"))
            self.assertEqual(code, 1)
            self.assertEqual(report["verdict"], "FAIL")
            self.assertIn("FLAG: fixture-model capital", output.getvalue())
            self.assertNotIn("private", output.getvalue())

    def test_main_writes_pass_and_fail_reports_from_mocked_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "result.json"
            md_path = Path(tmp) / "result.md"
            for text, expected_code, expected_verdict in (("Canberra.", 0, "PASS"),
                                                          ("Sydney.", 1, "FAIL"),
                                                          ("@" * 200, 1, "FAIL")):
                with self.subTest(expected_verdict=expected_verdict, text=text[:10]):
                    output = io.StringIO()
                    with patch.object(v, "load_prompts", return_value=[prompt()]), \
                            patch.object(v, "request_answer", return_value=self.answer(text)), \
                            contextlib.redirect_stdout(output):
                        code = v.main(["--server", "http://127.0.0.1:38375", "--model", "fixture-model",
                                       "--report", str(report_path), "--md", str(md_path)])
                    report = json.loads(report_path.read_text("utf-8"))
                    self.assertEqual(code, expected_code, output.getvalue())
                    self.assertEqual(report["verdict"], expected_verdict)
                    self.assertEqual(report["schema_version"], 1)
                    self.assertEqual(report["models"][0]["results"][0]["prompt_id"], "capital")
                    self.assertIn(expected_verdict, md_path.read_text("utf-8"))

    def test_main_operational_failure_writes_failed_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / "result.json"
            with patch.object(v, "load_prompts", return_value=[prompt()]), \
                    patch.object(v, "request_answer", side_effect=v.ValidationError("HTTP 503 from completion endpoint")), \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                code = v.main(["--server", "http://127.0.0.1:38375", "--model", "fixture-model",
                               "--report", str(report_path)])
            report = json.loads(report_path.read_text("utf-8"))
            self.assertEqual(code, 1)
            self.assertEqual(report["verdict"], "FAIL")
            row = report["models"][0]["results"][0]
            self.assertIsNone(row["latency_seconds"])
            self.assertIsNone(row["completion_tokens"])
            self.assertIn("FLAG: fixture-model capital", output.getvalue())

    def test_phone_without_endpoint_is_not_run_without_extra_completion(self):
        with patch.object(v, "load_prompts", return_value=[prompt()]), \
                patch.object(v, "request_answer", return_value=self.answer()) as request, \
                contextlib.redirect_stdout(io.StringIO()) as output:
            code = v.main(["--server", "http://127.0.0.1:38375", "--model", "fixture-model", "--phone"])
        self.assertEqual(code, 0)
        self.assertIn("phone: NOT_RUN", output.getvalue())
        self.assertEqual(request.call_count, 1)

    def test_phone_endpoint_receives_same_prompt_and_unreachable_hook_is_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "phone.json"
            argv = ["--server", "http://127.0.0.1:38375", "--model", "fixture-model", "--phone",
                    "--phone-url", "http://127.0.0.1:38376", "--report", str(path)]
            with patch.object(v, "load_prompts", return_value=[prompt()]), \
                    patch.object(v, "request_answer", return_value=self.answer()) as request, \
                    contextlib.redirect_stdout(io.StringIO()):
                code = v.main(argv)
            self.assertEqual(code, 0)
            self.assertEqual(request.call_count, 2)
            direct, phone = request.call_args_list
            self.assertEqual(direct.args[0], "http://127.0.0.1:38375/v1/chat/completions")
            self.assertEqual(phone.args[0], "http://127.0.0.1:38376/v1/chat/completions")
            self.assertEqual(direct.args[1:4], phone.args[1:4])
            self.assertEqual(json.loads(path.read_text("utf-8"))["phone"]["status"], "PASS")
            with patch.object(v, "load_prompts", return_value=[prompt()]), \
                    patch.object(v, "request_answer", side_effect=[self.answer(), v.ValidationError("unreachable")]) as request, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                code = v.main(argv)
            self.assertEqual(code, 0)
            self.assertEqual(request.call_count, 2)
            self.assertIn("phone: NOT_RUN", output.getvalue())
            self.assertEqual(json.loads(path.read_text("utf-8"))["phone"]["status"], "NOT_RUN")

    def test_credential_echo_is_removed_from_terminal_and_persisted_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            key, report_path, md_path = root / "fixture-key", root / "report.json", root / "report.md"
            key.write_text("test-only-credential\n", encoding="utf-8")
            with patch.object(v, "load_prompts", return_value=[prompt()]), \
                    patch.object(v, "request_answer", return_value=self.answer("Canberra. test-only-credential")) as request, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                code = v.main(["--server", "http://127.0.0.1:38375", "--model", "fixture-model",
                               "--api-key-file", str(key), "--report", str(report_path), "--md", str(md_path)])
            self.assertEqual(code, 0)
            self.assertEqual(request.call_args.args[4], "test-only-credential")
            for text in (output.getvalue(), report_path.read_text("utf-8"), md_path.read_text("utf-8")):
                self.assertNotIn("test-only-credential", text)

    def test_reported_token_overrun_fails_and_model_mismatch_warns(self):
        with patch.object(v, "request_answer", return_value=self.answer(completion_tokens=100)):
            row = v.run_models("http://127.0.0.1:38375/v1/chat/completions", ["fixture-model"],
                               [prompt()], 1, v.SYSTEM_PROMPT, None, 2.0)[0]["results"][0]
        self.assertEqual(row["verdict"], "FAIL")
        self.assertEqual(row["garble_reason"], "runaway_length")
        with patch.object(v, "request_answer", return_value=self.answer(reported_model="other-model")):
            row = v.run_models("http://127.0.0.1:38375/v1/chat/completions", ["fixture-model"],
                               [prompt()], 1, v.SYSTEM_PROMPT, None, 2.0)[0]["results"][0]
        self.assertEqual(row["verdict"], "WARN")
        self.assertTrue(row["warnings"])

    def test_all_protected_ports_and_embedded_credentials_are_rejected(self):
        urls = [f"http://127.0.0.1:{port}" for port in v.FORBIDDEN_PORTS]
        urls += ["http://user:credential@127.0.0.1:38375", "http://127.0.0.1:38375?token=x",
                 "http://127.0.0.1:38375/#fragment", "file:///tmp/model", "http://127.0.0.1:38375/other"]
        for url in urls:
            with self.subTest(url=url), self.assertRaises(ValueError):
                v.completion_url(url)
        for suffix in ("", "/v1", "/v1/chat/completions"):
            self.assertEqual(v.completion_url("http://127.0.0.1:38375" + suffix),
                             "http://127.0.0.1:38375/v1/chat/completions")

    def test_redirect_handler_refuses_following_protected_or_other_target(self):
        request = Request("http://127.0.0.1:38375/v1/chat/completions")
        for target in ("http://127.0.0.1:1235", "https://elsewhere.invalid/v1/chat/completions"):
            self.assertIsNone(v._NoRedirect().redirect_request(request, None, 302, "moved", {}, target))


class OwnServerLifecycle(unittest.TestCase):
    """Patch process-launch helpers; no runtime, GPU, or process signal is used."""
    def setUp(self):
        import gpu_link_autosetup as setup
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        binary, model = root / "llama-server", root / "fixture.gguf"
        binary.write_text("fixture executable; never launched", encoding="utf-8")
        binary.chmod(0o700)
        model.write_text("fixture model; never loaded", encoding="utf-8")
        self.args = SimpleNamespace(llama_server=str(binary), model_file=str(model),
                                    backend="metal", startup_timeout=1.0)
        self.server = MagicMock()
        self.server.process.pid = 98765
        self.server.process.poll.return_value = 0
        self.server.base_url = "http://127.0.0.1:38375"
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.choose = self.stack.enter_context(patch.object(setup, "choose_port", return_value=38375))
        self.launch = self.stack.enter_context(patch.object(setup, "launch_llama_server", return_value=self.server))
        self.health = self.stack.enter_context(patch.object(setup, "wait_healthy", return_value=True))
        self.stack.enter_context(patch.object(setup, "new_key", return_value="test-only-own-key"))
        self.snapshots = self.stack.enter_context(patch.object(v, "listener_snapshot", side_effect=[{"42 127.0.0.1:5000"}] * 2))
        for name in ("find_existing_servers", "detect_gpu", "ensure_model", "ensure_llama_server", "ensure_adb"):
            self.stack.enter_context(patch.object(setup, name, side_effect=AssertionError("forbidden discovery or setup")))

    def test_success_stops_only_returned_process_and_records_listener_check(self):
        with v.own_server(self.args, "fixture-alias") as (url, key, receipt):
            self.assertEqual(url, "http://127.0.0.1:38375/v1/chat/completions")
            self.assertEqual(key, "test-only-own-key")
            self.server.stop.assert_not_called()
        self.choose.assert_called_once_with(start=38300, span=100)
        self.health.assert_called_once_with(self.server, timeout=1.0)
        self.server.stop.assert_called_once_with(quiet=True)
        self.assertEqual(self.launch.call_args.args[2], 38375)
        self.assertEqual(self.launch.call_args.kwargs["alias"], "fixture-alias")
        self.assertTrue(receipt["strict_ports"])
        self.assertTrue(receipt["stopped"])
        self.assertTrue(receipt["listener_list_unchanged"])
        self.assertEqual(receipt["pid"], 98765)
        self.assertEqual(self.snapshots.call_count, 2)

    def test_unhealthy_startup_still_stops_spawned_server_once(self):
        self.health.return_value = False
        with self.assertRaises(v.ValidationError), v.own_server(self.args, "fixture-alias"):
            self.fail("unhealthy server must not be yielded")
        self.server.stop.assert_called_once_with(quiet=True)
        self.assertEqual(self.snapshots.call_count, 2)

    def test_exception_during_checks_still_stops_spawned_server_once(self):
        with self.assertRaisesRegex(RuntimeError, "simulated check failure"), v.own_server(self.args, "fixture-alias"):
            raise RuntimeError("simulated check failure")
        self.server.stop.assert_called_once_with(quiet=True)
        self.assertEqual(self.snapshots.call_count, 2)

    def test_changed_listeners_are_recorded_without_touching_other_processes(self):
        self.snapshots.side_effect = [{"42 127.0.0.1:5000"}, {"99 127.0.0.1:5001"}]
        with v.own_server(self.args, "fixture-alias") as (_, _, receipt):
            pass
        self.assertFalse(receipt["listener_list_unchanged"])
        self.server.stop.assert_called_once_with(quiet=True)


if __name__ == "__main__":
    unittest.main()

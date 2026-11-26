# SPDX-License-Identifier: Apache-2.0
"""Bounded demo checks, not a guarantee that a model never hallucinates."""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from http.client import HTTPException
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

HERE = Path(__file__).resolve().parent
SYSTEM_PROMPT = (HERE / "demo_system_prompt.txt").read_text(encoding="utf-8").strip()
MEANING = "PASS means passed these checks; these guards reduce, not eliminate, garbage and hallucinations."
FORBIDDEN_PORTS = frozenset({1234, 1235, 1236, 1237, 8765, 8767, 11434, 56795, 56740, 24001})
MAX_RESPONSE_BYTES = 1_048_576
UNCERTAINTY = re.compile(
    r"\b(?:(?:i(?:['’]m| am) )?not sure|(?:i )?(?:do not|don['’]t) know|"
    r"(?:can(?:not|['’]t)|could not) (?:yet )?(?:know|determine|predict|say)|"
    r"(?:no|not enough|insufficient) (?:reliable )?(?:information|data)|"
    r"(?:has not|hasn['’]t|have not|haven['’]t) (?:happened|occurred|been (?:held|played))|"
    r"not yet (?:happened|occurred|held|played|known|decided))\b", re.IGNORECASE)

try:
    from gpu_link_guard import garble_reason as _garble_reason
    DETECTOR = "gpu_link_guard.garble_reason"
except ImportError:
    from gpu_link_e2e import degenerate_text as _garble_reason
    DETECTOR = "gpu_link_e2e.degenerate_text (fallback)"


class ValidationError(RuntimeError):
    """A bounded, safe-to-display operational failure."""


def load_prompts(path: Path = HERE / "demo_prompts.json") -> list[dict[str, Any]]:
    prompts = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(prompts, list) or not prompts:
        raise ValueError("prompt set must be a nonempty list")
    ids: set[str] = set()
    for p in prompts:
        if not isinstance(p, dict):
            raise TypeError("each prompt must be an object")
        if not isinstance(p.get("id"), str) or not re.fullmatch(r"[a-z0-9_-]+", p["id"]) or p["id"] in ids:
            raise ValueError("prompt IDs must be unique lowercase identifiers")
        ids.add(p["id"])
        if not isinstance(p.get("text"), str) or not p["text"].strip() or not isinstance(p.get("note"), str):
            raise ValueError("prompt text and note are required")
        if p.get("kind") not in ("fact", "howto", "trap", "long"):
            raise ValueError("unknown prompt kind")
        if type(p.get("max_tokens")) is not int or not 1 <= p["max_tokens"] <= 4096:
            raise ValueError("max_tokens must be in 1..4096")
        groups, forbidden = p.get("expected_facts"), p.get("forbidden_patterns")
        if not isinstance(groups, list) or not isinstance(forbidden, list):
            raise TypeError("expected_facts and forbidden_patterns must be lists")
        patterns = list(forbidden)
        for group in groups:
            if not isinstance(group, list) or not group:
                raise ValueError("each expected-fact group must contain alternatives")
            patterns.extend(group)
        for pattern in patterns:
            if not isinstance(pattern, str) or not pattern:
                raise ValueError("fact and forbidden regexes must be nonempty strings")
            re.compile(pattern, re.IGNORECASE)
        for field in ("min_chars", "max_chars"):
            if field in p and (type(p[field]) is not int or p[field] < 1):
                raise ValueError(f"{field} must be a positive integer")
        if p.get("min_chars", 1) > p.get("max_chars", 16000):
            raise ValueError("min_chars must not exceed max_chars")
    return prompts


def _salad_reason(text: str, judge: Any) -> str | None:
    """Optional word-salad verdict (gpu_link_salad); None when no judge is configured."""
    try:
        import gpu_link_salad
        judge = judge if judge is not None else gpu_link_salad.default_judge()
        return gpu_link_salad.salad_reason(text, judge) if judge is not None else None
    except Exception:
        return None


LEAKED_TAG = re.compile(r"</?think(?:ing)?>|<\|[a-z_]{2,20}\|>|<unused\d+>", re.IGNORECASE)


def check_answer(prompt: dict[str, Any], text: str, finish_reason: str | None = None, salad_judge: Any = None) -> dict[str, Any]:
    failures: list[str] = []
    warnings: list[str] = []
    garble = _garble_reason(text)
    # Preserve shared reason strings even when the older detector returns prose.
    if garble == "long run of one repeated character":
        garble = "repeat_char"
    elif garble == "answer ends in a repeating loop":
        garble = "ngram_loop"
    limit = prompt.get("max_chars", min(16000, prompt["max_tokens"] * 12))
    if len(text) > limit:
        garble = garble or "runaway_length"
    if not garble and salad_judge is not False:
        garble = _salad_reason(text, salad_judge)
    if garble:
        failures.append(f"garbled: {garble}")
    if LEAKED_TAG.search(text):
        warnings.append("a thinking/special-token tag leaked into the answer (visible on the card)")
    if not text.strip():
        failures.append("empty answer")
    elif len(text.strip()) < prompt.get("min_chars", {"fact": 1, "howto": 20, "trap": 8, "long": 700}[prompt["kind"]]):
        warnings.append("answer too short for this prompt")
    for i, group in enumerate(prompt.get("expected_facts", []), 1):
        if not any(re.search(pattern, text, re.IGNORECASE) for pattern in group):
            failures.append(f"missing expected fact group {i}")
    for i, pattern in enumerate(prompt.get("forbidden_patterns", []), 1):
        if re.search(pattern, text, re.IGNORECASE):
            failures.append(f"forbidden pattern {i} matched")
    if prompt["kind"] == "trap" and not UNCERTAINTY.search(text):
        failures.append("trap answer lacks explicit uncertainty")
    if finish_reason == "length":
        warnings.append("answer reached the token limit; inspect for truncation")
    return {"verdict": "FAIL" if failures else "WARN" if warnings else "PASS",
            "failures": failures, "warnings": warnings, "garble_reason": garble}


def completion_url(server: str) -> str:
    try:
        u = urlsplit(server)
        port = u.port or (443 if u.scheme == "https" else 80)
        if (u.scheme not in ("http", "https") or not u.hostname or u.username or u.password
                or u.query or u.fragment or port in FORBIDDEN_PORTS):
            raise ValueError
        path = u.path.rstrip("/")
        if not path:
            path = "/v1/chat/completions"
        elif path == "/v1":
            path += "/chat/completions"
        elif not path.endswith("/chat/completions"):
            raise ValueError
        return urlunsplit((u.scheme, u.netloc, path, "", ""))
    except ValueError:
        raise ValueError("use an HTTP(S) base, /v1, or chat completions URL without credentials/query; protected ports are forbidden") from None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> None:
        return None  # Do not forward credentials or follow redirects to protected services.


def request_answer(url: str, model: str, prompt: dict[str, Any], system_prompt: str,
                   key: str | None, timeout: float) -> dict[str, Any]:
    messages = ([{"role": "system", "content": system_prompt}] if system_prompt else [])
    messages.append({"role": "user", "content": prompt["text"]})
    body = {"model": model, "messages": messages, "max_tokens": prompt["max_tokens"],
            "temperature": 0.2, "stream": False}
    # Same as the lanes: no hidden thinking (a thinking model such as Gemma 4 otherwise spends the whole small
    # token budget on reasoning_content and returns an empty answer; found in the first MacBook validator run).
    effort = os.environ.get("OPOS_GPU_LINK_REASONING_EFFORT", "none").strip()
    if effort and effort != "default":
        body["reasoning_effort"] = effort
        if effort == "none":
            body["chat_template_kwargs"] = {"enable_thinking": False}
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    request = Request(url, json.dumps(body).encode("utf-8"), headers, method="POST")
    start = time.monotonic()
    try:
        # Local and explicitly selected remote servers are contacted directly, never through an ambient proxy.
        with build_opener(ProxyHandler({}), _NoRedirect()).open(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
        elapsed = max(time.monotonic() - start, 0.000001)
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValidationError("response exceeds 1 MiB")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("choices"), list) or not data["choices"]:
            raise ValueError
        choice = data["choices"][0]
        if not isinstance(choice, dict) or not isinstance(choice.get("message"), dict):
            raise TypeError
        answer = choice["message"]["content"]
        if not isinstance(answer, str):
            raise TypeError
        reasoning_only = not answer.strip() and bool(str(choice["message"].get("reasoning_content") or "").strip())
        usage = data.get("usage") or {}
        if not isinstance(usage, dict):
            raise TypeError
        tokens = usage.get("completion_tokens")
        if type(tokens) is not int or tokens < 0:
            tokens = None
        reported_model = data.get("model")
        if reported_model is not None and not isinstance(reported_model, str):
            raise ValueError
        finish = choice.get("finish_reason")
        if finish is not None and not isinstance(finish, str):
            raise ValueError
        return {"answer": answer, "reasoning_only": reasoning_only, "latency_seconds": round(elapsed, 6), "completion_tokens": tokens,
                "tokens_per_second": round(tokens / elapsed, 3) if tokens is not None else None,
                "reported_model": reported_model, "finish_reason": finish}
    except HTTPError as error:
        error.close()
        raise ValidationError(f"HTTP {error.code} from completion endpoint") from None
    except (URLError, TimeoutError, OSError, HTTPException):
        raise ValidationError("completion endpoint unreachable or timed out") from None
    except (ValueError, TypeError, KeyError, IndexError, UnicodeError):
        raise ValidationError("malformed OpenAI chat completion response") from None


def verdict(values: list[str]) -> str:
    return "FAIL" if "FAIL" in values else "WARN" if "WARN" in values else "PASS"


def run_models(url: str, models: list[str], prompts: list[dict[str, Any]], runs: int,
               system_prompt: str, key: str | None, timeout: float, phone: bool = False) -> list[dict[str, Any]]:
    output = []
    successes = 0
    for model in models:
        results = []
        for run in range(1, runs + 1):
            for prompt in prompts:
                row = {"prompt_id": prompt["id"], "run": run, "kind": prompt["kind"]}
                try:
                    answer = request_answer(url, model, prompt, system_prompt, key, timeout)
                    successes += 1
                    row.update(answer)
                    row.update(check_answer(prompt, answer["answer"], answer["finish_reason"]))
                    if answer.get("reasoning_only"):
                        row["failures"].append("reasoning-only answer: the token budget went to hidden thinking")
                    if answer["completion_tokens"] is not None and answer["completion_tokens"] > prompt["max_tokens"]:
                        row["failures"].append("garbled: runaway_length (reported token budget exceeded)")
                        row["garble_reason"] = row["garble_reason"] or "runaway_length"
                    if answer["reported_model"] and answer["reported_model"] != model:
                        row["warnings"].append("response model differs from requested ID; verify alias mapping")
                    row["verdict"] = "FAIL" if row["failures"] else "WARN" if row["warnings"] else "PASS"
                except ValidationError as error:
                    if phone and successes == 0:
                        raise  # Best-effort hook must not hammer an absent/unsupported phone route.
                    row.update({"answer": "", "latency_seconds": None, "completion_tokens": None,
                                "tokens_per_second": None, "reported_model": None, "finish_reason": None,
                                "verdict": "FAIL", "failures": [str(error)], "warnings": [], "garble_reason": None})
                results.append(row)
        output.append({"model": model, "verdict": verdict([r["verdict"] for r in results]), "results": results})
    return output


def listener_snapshot() -> set[str] | None:
    """Read listener identities only, never process command lines or existing APIs."""
    executable = shutil.which("lsof")
    if not executable:
        return None
    try:
        result = subprocess.run([executable, "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpn"],
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=5, check=False)
        if result.returncode not in (0, 1) or (result.returncode == 1 and result.stdout):
            return None
        pid, listeners = "", set()
        for line in result.stdout.splitlines():
            if line.startswith("p"):
                pid = line[1:]
            elif line.startswith("n"):
                listeners.add(pid + " " + line[1:])
        return listeners
    except (OSError, subprocess.TimeoutExpired):
        return None


@contextmanager
def own_server(args: argparse.Namespace, model: str) -> Iterator[tuple[str, str, dict[str, Any]]]:
    import gpu_link_autosetup as setup
    binary, model_file = Path(args.llama_server).resolve(), Path(args.model_file).resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK) or not model_file.is_file():
        raise ValueError("own-server needs an existing executable --llama-server and local --model-file")
    before = listener_snapshot()
    receipt: dict[str, Any] = {"strict_ports": True, "stopped": False, "listener_list_unchanged": None}
    # No discovery, downloads, adb, GPU probes, or attachment to another runtime.
    with tempfile.TemporaryDirectory(prefix="gpu-link-validator-") as tmp:
        root = Path(tmp)
        key = setup.new_key()
        key_file = setup.write_key_file(key, root)
        port = setup.choose_port(start=38300, span=100)
        server = setup.launch_llama_server(binary, model_file, port, os.environ.copy(), root, args.backend,
                                           key_file, alias=model)
        receipt.update({"pid": server.process.pid, "port": port})
        try:
            if not setup.wait_healthy(server, timeout=args.startup_timeout):
                raise ValidationError("own llama-server failed its health check")
            key_file.unlink(missing_ok=True)
            yield completion_url(server.base_url), key, receipt
        finally:
            server.stop(quiet=True)  # The only process reference eligible for stopping is the one just spawned.
            receipt["stopped"] = server.process.poll() is not None
            after = listener_snapshot()
            if before is not None and after is not None:
                receipt["listener_list_unchanged"] = before == after


def _safe(value: Any, key: str | None = None) -> Any:
    """Do not persist credentials echoed back by an endpoint; keep terminal output inert."""
    if isinstance(value, str):
        value = value.replace(key, "[REDACTED]") if key else value
        return "".join(ch if ch in "\n\t" or (ord(ch) >= 32 and ord(ch) != 127) else "?" for ch in value)
    if isinstance(value, list):
        return [_safe(item, key) for item in value]
    if isinstance(value, dict):
        return {name: _safe(item, key) for name, item in value.items()}
    return value


def markdown_report(report: dict[str, Any]) -> str:
    def cell(value: Any) -> str:
        return str(value if value is not None else "unknown").replace("|", "\\|").replace("\n", " ").replace("\r", " ")
    lines = ["# GPU Link demo validator", "", f"Verdict: **{report['verdict']}**", "", MEANING, "",
             f"Detector: {report['detector']}", "", "Tokens/s = reported completion tokens / total request seconds (includes prompt processing).",
             "Missing usage is unknown, not zero. No first-token timing is measured.", ""]
    for target, models in [("server", report["models"]), ("phone", report["phone"].get("models", []))]:
        if not models:
            continue
        lines.extend([f"## {target}", "", "| Model | Prompt | Run | Verdict | Seconds | Tokens | Tokens/s | Reasons |",
                      "|---|---|---:|---|---:|---:|---:|---|"])
        for model in models:
            for row in model["results"]:
                values = [model["model"], row["prompt_id"], row["run"], row["verdict"], row["latency_seconds"],
                          row["completion_tokens"], row["tokens_per_second"], "; ".join(row["failures"] + row["warnings"])]
                lines.append("| " + " | ".join(cell(v) for v in values) + " |")
        lines.append("")
    lines.append("phone: " + report["phone"]["status"] + " " + report["phone"].get("reason", ""))
    return "\n".join(lines) + "\n"


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    route = p.add_mutually_exclusive_group(required=True)
    route.add_argument("--server", help="explicit OpenAI-compatible base or chat completions URL")
    route.add_argument("--own-server", action="store_true", help="launch only our own local llama-server; implies --strict-ports")
    p.add_argument("--model", help="model ID (own-server: alias for the supplied GGUF)")
    p.add_argument("--models", help="comma-separated model IDs; appended to --model, duplicates removed")
    p.add_argument("--api-key-file", type=Path)
    p.add_argument("--report", type=Path)
    p.add_argument("--md", type=Path)
    p.add_argument("--system-prompt", choices=("demo", "none"), default="demo")
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--timeout", type=float, default=60.0, help="timeout per completion in seconds")
    p.add_argument("--phone", action="store_true")
    p.add_argument("--phone-url", help="explicit adb-forwarded OpenAI-compatible endpoint; no adb commands are run")
    p.add_argument("--llama-server", help="existing executable path; never downloaded")
    p.add_argument("--model-file", help="existing local GGUF path; never downloaded")
    p.add_argument("--backend", choices=("cpu", "metal", "vulkan", "cuda"), default="metal")
    p.add_argument("--startup-timeout", type=float, default=120.0)
    p.add_argument("--strict-ports", action="store_true", help="own-server always uses this isolation, even without this flag")
    p.add_argument("--salad-model", help="tiny local GGUF (e.g. SmolLM2-135M) enabling the optional word-salad judge")
    p.add_argument("--perplexity-bin", help="llama-perplexity executable (default: next to --llama-server)")
    return p


def _setup_salad(args: argparse.Namespace) -> None:
    if not args.salad_model:
        return
    import gpu_link_salad
    binary = args.perplexity_bin or (str(Path(args.llama_server).with_name("llama-perplexity")) if args.llama_server else None)
    judge = gpu_link_salad.PerplexityJudge(binary, args.salad_model) if binary and Path(binary).is_file() and Path(args.salad_model).is_file() else None
    if judge is None:
        raise ValueError("word-salad judge needs existing --salad-model and llama-perplexity files")
    gpu_link_salad.set_default_judge(judge)


def _main(argv: list[str] | None = None) -> int:
    p = parser()
    args = p.parse_args(argv)
    models = list(dict.fromkeys(x.strip() for x in ([args.model] if args.model else []) + (args.models or "").split(",") if x.strip()))
    if not models or any(len(m) > 200 or any(ord(ch) < 32 or ord(ch) == 127 for ch in m) for m in models):
        p.error("supply --model or --models with nonempty printable model IDs")
    if not 1 <= args.runs <= 100 or not all(math.isfinite(n) and n > 0 for n in (args.timeout, args.startup_timeout)):
        p.error("runs must be 1..100 and timeouts must be finite and positive")
    if args.own_server and (not args.llama_server or not args.model_file or len(models) != 1 or args.api_key_file):
        p.error("own-server requires --llama-server, --model-file, one model alias, and uses its own temporary credential")
    key = None
    try:
        if args.phone_url:
            completion_url(args.phone_url)  # Validate before any request, even before the direct-server run.
        if args.server:
            completion_url(args.server)
        if args.report and args.md and args.report.resolve() == args.md.resolve():
            raise ValueError("JSON and Markdown outputs need different paths")
        _setup_salad(args)
        prompts = load_prompts()
        system = SYSTEM_PROMPT if args.system_prompt == "demo" else ""
        if args.api_key_file:
            key = args.api_key_file.read_text(encoding="utf-8").strip()
            if not key or any(ord(ch) < 32 or ord(ch) == 127 for ch in key):
                raise ValueError("credential file must contain one nonempty line")
        report: dict[str, Any] = {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "meaning": MEANING, "system_prompt": args.system_prompt, "detector": DETECTOR,
            "models": [], "warnings": [], "phone": {"status": "NOT_RUN", "reason": "not requested"}}
        if args.own_server:
            with own_server(args, models[0]) as (url, temporary_key, lifecycle):
                report["models"] = _safe(run_models(url, models, prompts, args.runs, system, temporary_key, args.timeout), temporary_key)
            report["own_server"] = lifecycle
        else:
            report["models"] = run_models(completion_url(args.server), models, prompts, args.runs, system, key, args.timeout)
        if args.phone:
            report["phone"] = {"status": "NOT_RUN", "reason": "no --phone-url configured"}
            if args.phone_url:
                try:
                    phone_models = run_models(completion_url(args.phone_url), models, prompts, args.runs, system, None, args.timeout, phone=True)
                    report["phone"] = {"status": verdict([m["verdict"] for m in phone_models]), "models": phone_models}
                except ValidationError as error:
                    report["phone"]["reason"] = str(error)
        statuses = [m["verdict"] for m in report["models"]]
        if args.phone:
            statuses.append("WARN" if report["phone"]["status"] == "NOT_RUN" else report["phone"]["status"])
        if args.own_server and report["own_server"]["listener_list_unchanged"] is not True:
            statuses.append("WARN")
            report["warnings"].append("listener list changed or could not be verified after own-server cleanup")
        report["verdict"] = verdict(statuses)
        report = _safe(report, key)
        print(markdown_report(report), end="")
        for why in report["warnings"]:
            print("FLAG: validator own_server " + why)
        for target in (report["models"], report["phone"].get("models", [])):
            for model in target:
                for row in model["results"]:
                    for why in row["failures"] + row["warnings"]:
                        print(f"FLAG: {model['model']} {row['prompt_id']} run {row['run']} {why}")
        if args.report:
            args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.md:
            args.md.write_text(markdown_report(report), encoding="utf-8")
        return int(report["verdict"] == "FAIL")
    except (OSError, ValueError, TypeError, RuntimeError) as error:
        # No raw endpoint response, credential, URL, or runtime log is ever printed on failure.
        message = str(error) if isinstance(error, ValidationError) else "invalid configuration or local file operation failed"
        print("FLAG: validator setup " + _safe(message, key))
        return 1


def main(argv: list[str] | None = None) -> int:
    try:
        return _main(argv)
    except SystemExit as error:
        return int(bool(error.code))  # Keep the CLI's documented 0/1 contract, including argument errors.


if __name__ == "__main__":
    raise SystemExit(main())

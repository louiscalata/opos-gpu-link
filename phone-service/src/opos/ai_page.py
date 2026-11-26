# SPDX-License-Identifier: Apache-2.0
"""AI mode: durable phone, GPU and sequential on-device model answers."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from copy import deepcopy
from typing import Any

from opos import ai_answers, ai_model_pool, ai_stream_budget, appdoc, apps, assist, muse

try:
    from opos import gpu_link_server
except ImportError:
    gpu_link_server = None

try:
    from opos.gpu_link import answer_noun, computer_noun, computer_title
    from opos.gpu_link import display_label as _pc_display
except ImportError:
    def _pc_display(label: Any) -> Any:
        return label

    def computer_noun(pc_label: Any) -> str:
        return "computer"

    def computer_title(noun: str) -> str:
        return noun[:1].upper() + noun[1:] if noun else "Computer"

    def answer_noun(where: Any, pc_label: Any) -> str:
        return "computer"

# The placeholder place for a computer lane. The snapshot keeps it exactly, because the Android app
# matches it (PaneKeys.shownWhere); the page script words it for the paired computer.
PC_WHERE = "on the PC's GPU"


def _shown_answer(answer: dict | None) -> dict | None:
    """Map a stored computer answer's saved pairing label to its screen name, without storing it."""
    if not answer or not answer.get("where"):
        return answer
    shown = _pc_display(answer["where"])
    return answer if shown == answer["where"] else {**answer, "where": shown}

QUESTIONS = (
    "Explain why the sky looks blue in words a ten-year-old would understand.",
    "Suggest five things neighbours can do together to make a small public garden welcoming.",
    "Write a detailed guide to starting a public library of useful things, such as tools, games and kitchen equipment. "
    "Use twenty numbered sections, with about eighty words in each section. Cover choosing a space, "
    "asking neighbours what they need, collecting donations, checking safety, keeping a catalogue, borrowing rules, "
    "repairs, volunteers, accessibility, welcoming newcomers, costs, opening hours, teaching skills, sharing fairly, "
    "handling lost items, measuring usefulness and planning the next year. Give practical examples throughout, "
    "and finish with a sample plan for the first month.",
)
PRESETS = tuple(
    {"label": label, "question": question}
    for label, question in zip(
        ("Why the sky is blue", "A welcoming garden", "A long guide (20 sections)"), QUESTIONS, strict=True
    )
)
DISCLOSURE = "Compare answers here and on a paired computer. That computer can see what you ask here."
APPEND_INTERVAL = 0.25
POOL_START_TIMEOUT = 90.0
RESERVED_PORTS = {8080, 8081, 8765, 8767, 1234, 1235, 1236, 11434, 11435, 4173}


def _route() -> muse.Route | None:
    return assist.local_route(free=assist.free_mb())


def _service() -> Any:
    return gpu_link_server.service() if gpu_link_server is not None else None


class _DecodeGate:
    """Give pool models FIFO turns and keep the phone decoder out of each turn."""

    def __init__(self) -> None:
        self.condition = threading.Condition()
        self.queue: deque[object] = deque()
        self.active: object | None = None
        self.phone_pending = 0

    def reserve_phone(self) -> None:
        with self.condition:
            self.phone_pending += 1
            self.condition.notify_all()

    def phone_turn(self, cancelled: threading.Event) -> bool:
        with self.condition:
            while self.active is not None:
                if cancelled.is_set():
                    return False
                self.condition.wait(0.05)
            return not cancelled.is_set()

    def release_phone(self) -> None:
        with self.condition:
            self.phone_pending -= 1
            self.condition.notify_all()

    def reserve_pool(self) -> object:
        with self.condition:
            ticket = object()
            self.queue.append(ticket)
            self.condition.notify_all()
            return ticket

    def pool_turn(self, ticket: object, cancelled: threading.Event) -> bool:
        with self.condition:
            while True:
                if cancelled.is_set():
                    self.release_pool(ticket)
                    return False
                if self.active is None and self.phone_pending == 0 and self.queue and self.queue[0] is ticket:
                    self.queue.popleft()
                    self.active = ticket
                    return True
                self.condition.wait(0.05)

    def release_pool(self, ticket: object) -> None:
        with self.condition:
            if self.active is ticket:
                self.active = None
            else:
                try:
                    self.queue.remove(ticket)
                except ValueError:
                    pass
            self.condition.notify_all()


_DECODE_GATE = _DecodeGate()


def _chosen_panes(panes: Any) -> tuple[list[str], dict[str, ai_model_pool.Model]]:
    if not isinstance(panes, list) or not panes or any(pane not in ai_answers.PANES for pane in panes):
        raise ValueError("Choose an available phone, GPU, or model pane.")
    if len(set(panes)) != len(panes):
        raise ValueError("Choose each pane once.")
    configured = {item.pane: item for item in ai_model_pool.models()}
    link = _service()
    advertised = {item["pane"] for item in ((link.snapshot().get("pc") or {}).get("models") or [])
                  if item.get("id")} if link is not None else set()
    chosen = [
        pane
        for pane in panes
        if (pane != "gpu" or link is not None)
        and (pane not in ai_answers.PC_PANES[1:] or pane in advertised)
        and (pane not in ai_model_pool.PANES or pane in configured)
    ]
    if not chosen:
        raise ValueError("GPU Link is off." if panes == ["gpu"] else "No selected model is available.")
    return chosen, configured


class PhoneWorker:
    """Own one answer's thread and close its stream in the reading thread."""

    def __init__(self, answers: ai_answers.AnswerStore, ident: str, safe: bool = False) -> None:
        self.answers = answers
        self.ident = ident
        self.cancelled = threading.Event()
        self.problem: str | None = None
        self.live_speed: int | None = None
        self.safe_seed: int | None = secrets.randbits(31) if safe else None
        self._phone_reserved = False
        self.thread = threading.Thread(target=self._run, name="ai-phone-" + ident, daemon=True)

    def start(self) -> None:
        """Start this answer exactly once."""
        _DECODE_GATE.reserve_phone()
        self._phone_reserved = True
        try:
            self.thread.start()
        except Exception:
            self._cleanup()
            raise

    def _wait_turn(self) -> bool:
        while not self.cancelled.is_set():
            answer = self.answers.get(self.ident)
            if answer is None or answer["state"] in ai_answers.FINAL:
                return False
            if answer["state"] == "waiting":
                return True
            self.cancelled.wait(0.05)
        return False

    def _end(self, code: str) -> None:
        answer = self.answers.get(self.ident)
        if answer is not None and answer["state"] not in ai_answers.FINAL:
            if self.cancelled.is_set():
                self.answers.cancel(self.ident)
            else:
                self.answers.fail(self.ident, code)

    def _safe_open(self, request: urllib.request.Request, timeout: float | None = None) -> Any:
        """Adjust only the completion body; retain Muse's no-proxy/no-redirect transport."""
        if request.get_method() == "POST" and request.full_url.endswith("/chat/completions"):
            payload = json.loads(request.data)
            payload.update(seed=self.safe_seed, temperature=0.1, repeat_penalty=1.1)
            request.data = json.dumps(payload).encode("utf-8")
        return muse._open_no_redirect(request, timeout=timeout)

    def _read(self, route: muse.Route, question: str, max_tokens: int = 4096, open_error: str = "no_model") -> None:
        offset = 0
        pending = b""
        last = float("-inf")
        first_piece = None
        last_speed = 0.0
        pieces = 0
        try:
            options = {"opener": self._safe_open} if self.safe_seed is not None else {}
            stream = muse.stream(
                route, question, cancel=self.cancelled, max_tokens=max_tokens,
                timeout=ai_stream_budget.stream_timeout(max_tokens), **options)
        except muse.MuseError:
            self._end(open_error)
            return
        with stream:
            self.answers.note(self.ident, model=stream.route.name[:64], where=stream.route.where[:64])
            for piece in stream:
                if self.cancelled.is_set():
                    return
                now = time.monotonic()
                pieces += 1
                if first_piece is None:
                    first_piece = last_speed = now
                if now - last_speed >= 1:
                    self.live_speed = round(pieces / (now - first_piece))
                    last_speed = now
                pending += ai_answers.clean(piece).encode("utf-8")
                if offset + len(pending) > ai_answers.MAX_ANSWER_BYTES:
                    raise ai_answers.TooLongError(offset)
                if pending and time.monotonic() - last >= APPEND_INTERVAL:
                    self.answers.append(self.ident, offset, pending)
                    offset += len(pending)
                    pending = b""
                    last = time.monotonic()
            if self.cancelled.wait(max(0, APPEND_INTERVAL - (time.monotonic() - last))):
                return
            self.answers.note(self.ident, tokens=stream.tokens, tps=stream.tps)
            self.answers.append(self.ident, offset, pending, done=True, finish=stream.finish or "stop")

    def _work(self) -> str | None:
        if not self._wait_turn() or not _DECODE_GATE.phone_turn(self.cancelled):
            return None
        route = _route()
        if route is None:
            return "no_model"
        answer = self.answers.begin(self.ident)
        self._read(route, answer["question"])
        return None

    def _cleanup(self) -> None:
        if self._phone_reserved:
            self._phone_reserved = False
            _DECODE_GATE.release_phone()

    def _run(self) -> None:
        code = None
        try:
            code = self._work()
        except ai_answers.TooLongError:
            code = "too_long"
        except Exception:  # Thread boundary: persist a safe code, never prompt or error text.
            code = "stream_error"
        finally:
            try:
                self._cleanup()
            except Exception:
                code = code or "stream_error"
            self.live_speed = None
            if code is not None or self.cancelled.is_set():
                try:
                    self._end(code or "cancelled")
                except Exception:  # Thread boundary: retain a safe failure for the next snapshot to retry.
                    self.problem = "storage_error"


def _free_port() -> int:
    for _ in range(32):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        if port not in RESERVED_PORTS:
            return port
    raise OSError("no available pool port")


class PoolWorker(PhoneWorker):
    """Own one FIFO pool turn, including its llama-server process lifetime."""

    def __init__(
        self, answers: ai_answers.AnswerStore, ident: str, model: ai_model_pool.Model, phone_ident: str | None,
        safe: bool = False,
    ) -> None:
        super().__init__(answers, ident, safe=safe)
        self.model = model
        self.phone_ident = phone_ident
        self.ticket = _DECODE_GATE.reserve_pool()
        self._process_lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self.thread.name = "ai-pool-" + ident

    def start(self) -> None:
        try:
            self.thread.start()
        except Exception:
            self._cleanup()
            raise

    def stop_process(self) -> None:
        """End the server now so cancellation also interrupts a blocked HTTP read."""
        with self._process_lock:
            process = self._process
            if process is None:
                return
            try:
                if process.poll() is None:
                    try:
                        process.terminate()
                    except ProcessLookupError:
                        pass
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            finally:
                self._process = None

    def _wait_phone(self) -> bool:
        while not self.cancelled.is_set():
            if self.phone_ident is None:
                return True
            phone = self.answers.get(self.phone_ident)
            if phone is None or phone["state"] in ai_answers.FINAL:
                return True
            self.cancelled.wait(0.05)
        return False

    def _ready(self, port: int) -> bool:
        deadline = time.monotonic() + POOL_START_TIMEOUT
        while not self.cancelled.is_set() and time.monotonic() < deadline:
            with self._process_lock:
                if self._process is None or self._process.poll() is not None:
                    return False
            for endpoint in ("/health", "/v1/models"):
                try:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    request = urllib.request.Request(f"http://127.0.0.1:{port}{endpoint}", method="GET")
                    with muse._open_no_redirect(request, timeout=min(0.5, remaining)) as response:
                        if response.status == 200:
                            return True
                except (OSError, urllib.error.URLError, ValueError):
                    pass
            self.cancelled.wait(min(0.2, max(0, deadline - time.monotonic())))
        return False

    def _work(self) -> str | None:
        self.answers.note(self.ident, model=self.model.label, where="on this phone")
        if not self._wait_turn() or not self._wait_phone():
            return None
        if not _DECODE_GATE.pool_turn(self.ticket, self.cancelled):
            return None
        try:
            size = self.model.path.stat().st_size
            if self.model.path.resolve(strict=True).parent != self.model.path.parent.resolve(strict=True):
                return "model_start"
        except OSError:
            return "model_start"
        file_mb = (size + 1048575) // 1048576
        free = assist.free_mb()
        if free is None or free < file_mb * 1.25 + 300:
            return "low_memory"
        if self.cancelled.is_set():
            return None
        answer = self.answers.begin(self.ident)
        binary = shutil.which(os.environ.get("OPOS_LLAMA_SERVER") or "llama-server")
        if binary is None:
            return "model_start"
        try:
            port = _free_port()
            args = [
                binary,
                "-m",
                str(self.model.path),
                "--alias",
                self.model.slug,
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "-c",
                str(self.model.ctx),
                "-t",
                str(self.model.threads),
                "--no-webui",
            ]
            log_path = self.model.path.parent / f"pool-{self.model.pane}.log"
            log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
            with os.fdopen(log_fd, "ab") as log:
                with self._process_lock:
                    if self.cancelled.is_set():
                        return None
                    self._process = subprocess.Popen(
                        args, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, close_fds=True
                    )
        except (OSError, ValueError):
            return "model_start"
        if not self._ready(port):
            return "model_start"
        route = muse.Route(
            key=self.model.slug,
            name=self.model.label,
            where="on this phone",
            base_url=f"http://127.0.0.1:{port}/v1",
            model=self.model.slug,
            verify_model=True,
        )
        self._read(route, answer["question"], max_tokens=self.model.max_tokens, open_error="stream_error")
        return None

    def _cleanup(self) -> None:
        try:
            self.stop_process()
        finally:
            _DECODE_GATE.release_pool(self.ticket)


class PageState:
    """Serialize page actions and number complete display snapshots."""

    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.boot = secrets.token_hex(4)
        self.rev = 0
        self.previous: dict | None = None
        self.workers: dict[str, PhoneWorker] = {}

    def _views(
        self, answers: ai_answers.AnswerStore, link: Any
    ) -> tuple[dict | None, dict | None, dict[str, dict | None], dict[str, dict | None], dict | None, int]:
        # The public APIs offer no shared lock. Retry overlapping writes rather
        # than publishing a phone answer and a GPU answer from different revisions.
        for _ in range(20):
            before = link.snapshot() if link is not None else None
            revision = answers.rev
            phone = answers.current("phone") or answers.latest("phone")
            gpu = answers.current("gpu") or answers.latest("gpu")
            pool = {pane: answers.current(pane) or answers.latest(pane) for pane in ai_model_pool.PANES}
            extra = {pane: answers.current(pane) or answers.latest(pane) for pane in ai_answers.PC_PANES[1:]}
            after = link.snapshot() if link is not None else None
            if revision == answers.rev and before == after:
                return phone, gpu, pool, extra, after, revision
        raise OSError("AI mode is busy; try again.")

    def snapshot(self) -> dict:
        """Return both panes together, with a revision for store and link changes."""
        with self.lock:
            for job in self.workers.values():
                if not job.thread.is_alive() and job.problem is not None:
                    # Never invent an answer outside the store. If storage is
                    # still unavailable, refuse the snapshot instead of hiding it.
                    job._end(job.problem)
                    job.problem = None
            self.workers = {key: job for key, job in self.workers.items() if job.thread.is_alive()}
            models = ai_model_pool.models()
            phone, gpu, pool, extra, link, revision = self._views(ai_answers.shared(), _service())
            route = _route()
            gpu_model = link["model"] if link is not None else None
            pc = link["pc"] if link is not None else None
            # Reuse the app's model-details text. Never relabel a finished answer
            # or one belonging to an earlier PC with this PC's active model.
            lead_label = (pc or {}).get("lead_label")
            noun = computer_noun((pc or {}).get("label"))
            same_pc = bool(pc and (not gpu or
                           gpu["state"] not in ai_answers.FINAL and
                           (not gpu["where"] or _pc_display(gpu["where"]) == pc["label"])))
            pc_models = list((pc or {}).get("models") or [])
            visible = {item.get("pane") for item in pc_models}
            pc_models.extend({"pane": pane, "id": "", "label": (answer["model"] or f"{computer_title(answer_noun(answer.get('where'), (pc or {}).get('label')))} {pane}"),
                              "maker": "", "live": False, "live_speed": None}
                             for pane, answer in extra.items() if answer is not None and pane not in visible)
            body = {
                "phone": {
                    "model": (phone["model"] if phone else "") or (route.name if route else ""),
                    "where": (phone["where"] if phone else "") or (route.where if route else "on this phone"),
                    "ready": route is not None and not (phone and phone["error"] == "no_model"),
                    "answer": phone,
                    "live_speed": (
                        self.workers[phone["id"]].live_speed
                        if phone and phone["state"] == "answering" and phone["id"] in self.workers
                        else None
                    ),
                },
                "gpu": {
                    **({"lead_label": lead_label} if lead_label is not None else {}),
                    "model": (lead_label if same_pc else None) or (gpu["model"] if gpu else "") or (gpu_model["name"] if gpu_model else ""),
                    "where": _pc_display((gpu["where"] if gpu else "") or PC_WHERE),
                    "ready": bool(
                        gpu_model
                        and gpu_model["state"] == "ready"
                        and pc
                        and pc["live"]
                        and pc.get("main_live", pc["live"])
                        and pc["state"] == "ready"
                        and not link.get("storage_notice")
                    ),
                    "answer": _shown_answer(gpu),
                    "link": link,
                },
                "models": [
                    {
                        "pane": item.pane,
                        "kind": "phone",
                        "label": item.label,
                        "maker": item.maker,
                        "model": item.label,
                        "where": "on this phone",
                        "ready": True,
                        "answer": pool[item.pane],
                        "live_speed": (
                            self.workers[pool[item.pane]["id"]].live_speed
                            if pool[item.pane]
                            and pool[item.pane]["state"] == "answering"
                            and pool[item.pane]["id"] in self.workers
                            else None
                        ),
                        "file_mb": item.file_mb,
                    }
                    for item in models
                ] + [
                    {
                        "pane": item["pane"],
                        "kind": "pc",
                        "label": item["label"],
                        "maker": item["maker"],
                        "model": (extra[item["pane"]]["model"] if extra[item["pane"]] else "") or item["label"],
                        "where": PC_WHERE,
                        "ready": bool(pc and pc["live"] and item["live"] and not link.get("storage_notice")),
                        "answer": _shown_answer(extra[item["pane"]]),
                        "live_speed": item.get("live_speed") if extra[item["pane"]] and
                        extra[item["pane"]]["state"] == "answering" else None,
                    }
                    for item in pc_models if item.get("pane") in extra
                ],
                "presets": deepcopy(list(PRESETS)),
            }
            # Include store rev even if a change affects an older queued answer.
            comparison = {"store_rev": revision, **body}
            if comparison != self.previous:
                self.rev += 1
                self.previous = deepcopy(comparison)
            return {"boot": self.boot, "rev": self.rev, **body}

    def ask(self, data: dict, *, safe: bool = False) -> None:
        """Validate once, store each question and start each local answer worker."""
        question = data.get("question")
        if not isinstance(question, str):
            raise ValueError("Enter a question.")
        question = ai_answers.clean(question)
        if not question.strip():
            raise ValueError("Enter a question.")
        if len(question.encode("utf-8")) > ai_answers.MAX_QUESTION_BYTES:
            raise ValueError("Keep the question to 4,096 bytes or fewer.")
        panes, configured = _chosen_panes(data.get("panes"))
        answers = ai_answers.shared()
        if any(pane in ai_answers.PC_PANES for pane in panes) and answers.startup_notice:
            raise ValueError(answers.startup_notice)
        if any(answers.current(pane) is not None for pane in panes):
            raise ValueError("Wait for this answer, or stop it.")
        held = answers.snapshot()["answers"]
        unfinished = sum(row["state"] not in ai_answers.FINAL for row in held)
        if unfinished + len(panes) > ai_answers.MAX_ANSWERS:
            raise ai_answers.FullError("full")
        stored = []
        try:
            for pane in panes:
                stored.append((pane, answers.ask(pane, question)))
        except Exception:
            for _, answer in stored:
                try:
                    answers.fail(answer["id"], "storage_error")
                except (ai_answers.StateError, OSError):
                    pass
            raise
        self._start_jobs(answers, stored, configured, safe=safe)

    def _start_jobs(
        self,
        answers: ai_answers.AnswerStore,
        stored: list[tuple[str, dict]],
        configured: dict[str, ai_model_pool.Model],
        *, safe: bool = False,
    ) -> None:
        phone_ident = next((answer["id"] for pane, answer in stored if pane == "phone"), None)
        jobs = []
        for pane, answer in stored:
            if pane == "phone":
                jobs.append(PhoneWorker(answers, answer["id"], safe=safe))
            elif pane in configured:
                jobs.append(PoolWorker(answers, answer["id"], configured[pane], phone_ident, safe=safe))
        # Reserve the phone decoder before any pool thread can take a ticket.
        for job in sorted(jobs, key=lambda item: isinstance(item, PoolWorker)):
            self.workers[job.ident] = job
            try:
                job.start()
            except RuntimeError:
                job._cleanup()
                try:
                    answers.fail(job.ident, "worker_start")
                except OSError:
                    job.problem = "worker_start"
                    raise
                del self.workers[job.ident]

    def cancel(self, ident: str) -> None:
        """Stop local work or ask the link to drop a GPU lease before cancelling."""
        answers = ai_answers.shared()
        answer = answers.get(ident) if isinstance(ident, str) else None
        if answer is None:
            raise ValueError("That answer was not found.")
        job = self.workers.get(ident)
        if job is not None:
            job.cancelled.set()
        link = _service()
        try:
            if answer["pane"] in ai_answers.PC_PANES and link is not None:
                link.cancel(ident)
            else:
                answers.cancel(ident)
        finally:
            if isinstance(job, PoolWorker):
                job.stop_process()

    def retry(self, data: dict) -> None:
        """Rerun one lane's current question, replacing a stuck, paused, failed or finished answer.

        The caller names the answer it saw. If the lane has moved on since (a double tap, a replayed
        request), the Retry is refused so it can never cancel a fresh answer.
        """
        pane = data.get("pane")
        if not isinstance(pane, str) or pane not in ai_answers.PANES:
            raise ValueError("Choose a model to retry.")
        answers = ai_answers.shared()
        latest = answers.current(pane) or answers.latest(pane)
        if latest is None:
            raise ValueError("There is no answer to retry.")
        expect = data.get("id")
        if expect is not None and expect != latest["id"]:
            raise ValueError("That answer has already been replaced.")
        if expect is None and latest["state"] not in ai_answers.FINAL:
            # Without the answer's id a delayed request could end a fresh answer.
            raise ValueError("Name the answer to retry.")
        question = latest["question"]
        if not question.strip():
            raise ValueError("There is no question to retry.")
        # Check that the lane can take work before ending the old answer, so a refused Retry
        # leaves a paused PC answer exactly as it was.
        _chosen_panes([pane])
        if latest["state"] not in ai_answers.FINAL:
            self.cancel(latest["id"])
        # The r14 PC work protocol carries no sampler fields. It still gets a fresh answer;
        # local phone/pool workers can apply the safer completion payload through Muse's opener.
        self.ask({"question": question, "panes": [pane]}, safe=data.get("safe") == 1)

    def close(self) -> None:
        """Cancel and join owned workers; tests call this before removing storage."""
        with self.lock:
            jobs = list(self.workers.values())
            for job in jobs:
                job.cancelled.set()
        for job in jobs:
            if isinstance(job, PoolWorker):
                job.stop_process()
        for job in jobs:
            if job.thread.ident is not None:
                job.thread.join(muse.STREAM_IDLE_S + 5)
            if job.thread.is_alive():
                raise RuntimeError("AI mode worker did not stop.")
        with self.lock:
            self.workers.clear()


_STATE = PageState()


def snapshot() -> dict:
    """Return the app's complete token-protected data."""
    return _STATE.snapshot()


def post(data: Any) -> tuple[int, dict]:
    """Apply one action and return a fresh snapshot, or a short refusal sentence."""
    if not isinstance(data, dict):
        return 400, {"error": "Choose an AI mode action."}
    with _STATE.lock:
        try:
            action = data.get("action")
            if action == "ask":
                _STATE.ask(data)
            elif action == "cancel":
                _STATE.cancel(data.get("id"))
            elif action == "retry":
                _STATE.retry(data)
            elif action in ("allow", "deny", "reopen", "forget"):
                link = _service()
                if link is None:
                    raise ValueError("GPU Link is off.")
                if action in ("allow", "deny"):
                    if getattr(link, action)(data.get("code")) is False:
                        raise ValueError("That request is no longer waiting.")
                elif action == "forget":
                    if link.forget(data.get("expect")) is False:
                        raise ValueError(
                            "There is no computer request to change."
                            if link.snapshot()["pc"] is None
                            else "That is a different computer now."
                        )
                elif getattr(link, action)() is False:
                    raise ValueError("There is no computer request to change.")
            else:
                raise ValueError("Choose an AI mode action.")
            return 200, snapshot()
        except ai_answers.FullError:
            return 400, {"error": "Stop an unfinished answer before asking again."}
        except ai_answers.StateError:
            return 400, {"error": "That answer has already ended."}
        except OSError:
            return 500, {"error": "The phone could not save the answer."}
        except ValueError as err:
            return 400, {"error": str(err)}


# Inline assets follow the existing app-page pattern: this lane owns no shared
# static route, and appdoc.render accepts its script and CSS as strings.
_CSS = """
html,body,button,input{font-family:"Inter Tight",sans-serif;font-size:max(18px,1rem)}
h1,h2,.speed{font-family:Newsreader,serif}
#list,#thumb{min-width:0}
.pane{min-width:0;margin-top:16px}
.pane p{margin:0 0 8px}
.speed{font-size:32px;line-height:1.15}
.answer{white-space:pre-wrap;overflow-wrap:anywhere;height:30vh;max-height:30vh;overflow-y:auto;box-sizing:border-box;border:1px solid var(--fg);padding:12px}
#err:not(:empty){border:3px double var(--fg);padding:8px}
#question{width:100%;min-height:48px;background:var(--bg);color:var(--fg);border:1px solid var(--fg);font:inherit}
#controls{margin-bottom:16px}
#presets{display:flex;flex-wrap:wrap;gap:8px}
#presets button{font:inherit;width:auto;margin:0;padding:8px}
button:disabled{opacity:.6;cursor:wait}
button:disabled::after{content:"\u00a0unavailable"}
#gpu-cable{font-size:24px;font-weight:600;border:1px solid var(--fg);padding:6px 10px}
#gpu-cable[data-cable=wait]{border:3px solid var(--fg)}
#gpu-cable[data-cable=out]{border:3px double var(--fg)}
#pc-extra{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:16px}
#pc-extra .pane{display:block;grid-row:auto;margin-top:16px}
#pc-extra .answer{height:30vh;max-height:30vh}
[hidden]{display:none!important}
html[data-pane] main{display:block}
html[data-pane] #gap{display:none}
html[data-pane=phone] #thumb,html[data-pane=gpu] #list{display:none}
html[data-pane] #list,html[data-pane] #thumb{padding:0}
@media(min-width:1000px){
html:not([data-pane]) #list,html:not([data-pane]) #thumb{display:contents}
html:not([data-pane]) #ai-title{grid-column:1;grid-row:1}
html:not([data-pane]) #controls{grid-column:1;grid-row:2}
html:not([data-pane]) #gap{grid-column:2;grid-row:1 / span 12}
html:not([data-pane]) .pane{display:grid;grid-template-rows:subgrid;grid-row:3 / span 9;margin-top:0}
html:not([data-pane]) #phone-pane{grid-column:1}
html:not([data-pane]) #gpu-pane{grid-column:3}
html:not([data-pane]) .pane h2{grid-row:1}
html:not([data-pane]) .model{grid-row:2}
html:not([data-pane]) .speed{grid-row:3}
html:not([data-pane]) .details{grid-row:4}
html:not([data-pane]) #gpu-cable{grid-row:5}
html:not([data-pane]) #gpu-disclosure{grid-row:6}
html:not([data-pane]) .answer{grid-row:7;height:55vh;max-height:55vh}
html:not([data-pane]) .stop{grid-row:8;align-self:start}
html:not([data-pane]) #link-controls{grid-row:9}
html:not([data-pane]) #pc-extra{grid-column:1 / 4;grid-row:13}
html[data-fanout=true]:not([data-pane]) main{max-width:1800px;grid-template-columns:minmax(200px,1fr) var(--hinge) repeat(4,minmax(180px,1fr))}
html[data-fanout=true]:not([data-pane]) #pc-extra{grid-column:4 / 7;grid-row:3 / span 9;align-items:start}
html:not([data-pane]) .nav{grid-column:3;grid-row:12}
}
@media(prefers-reduced-motion:reduce){main{transition:none;animation:none}}
"""

_LIST = """
<h1 id="ai-title">AI mode</h1>
<div id="controls">
<label for="question">Question</label><input id="question" type="text" autocomplete="off">
<button id="ask" type="button" class="main">Ask both models</button>
<div id="presets" aria-label="Preset questions"></div>
<p id="err" role="status"></p>
</div>
<section id="phone-pane" class="pane" aria-labelledby="phone-title">
<h2 id="phone-title">Phone</h2>
<p id="phone-model" class="model" hidden></p>
<p id="phone-speed" class="speed" role="status">Waiting for a snapshot</p>
<p id="phone-state" class="details" hidden></p>
<div id="phone-answer" class="answer" tabindex="0" role="region" aria-label="Phone answer"></div>
<button id="phone-stop" class="stop" type="button" hidden>Stop phone answer</button>
</section>
"""
_THUMB = """
<section id="gpu-pane" class="pane" aria-labelledby="gpu-title">
<h2 id="gpu-title">Computer GPU</h2>
<p id="gpu-model" class="model" hidden></p>
<p id="gpu-speed" class="speed" role="status">Waiting for a snapshot</p>
<p id="gpu-state" class="details" hidden></p>
<p id="gpu-cable" role="status" hidden></p>
<p id="gpu-disclosure">This computer can see what you ask here.</p>
<div id="gpu-answer" class="answer" tabindex="0" role="region" aria-label="Computer GPU answer"></div>
<button id="gpu-stop" class="stop" type="button" hidden>Stop GPU answer</button>
<div id="link-controls">
<div id="enrol" hidden><p id="enrol-text"></p>
<button id="deny" type="button" class="main">Not now</button>
<button id="allow" type="button">Allow</button></div>
<button id="reopen" type="button" hidden>Allow computer requests again</button>
<button id="forget" type="button" hidden>Forget this computer</button>
</div>
</section>
<div id="pc-extra" aria-label="Additional model lanes"></div>
"""
_SCRIPT = r"""
function G(id){return document.getElementById(id)}
function text(id,value){var e=G(id);if(e.textContent!==value)e.textContent=value}
// The paired computer's noun from its display name, as the app and gpu_link.computer_noun name it:
// "MacBook" or "Mac" for a Mac, "PC" for another paired computer, else "computer".
function nounOf(label){
 if(typeof label!=='string'||!label.trim())return 'computer';
 if(/\b(?:MacBook|MBP(?![A-Za-z]))/i.test(label))return 'MacBook';
 if(/\b(?:iMac|Mac(?:intosh|mini|Studio|Pro)?)(?![A-Za-z])/i.test(label))return 'Mac';
 return 'PC';
}
function noun(){var l=current&&current.gpu&&current.gpu.link;return nounOf(l&&l.pc&&l.pc.label)}
// A saved answer names the computer that wrote it (its where), not whichever one is paired now.
function answerNoun(a){var w=a&&typeof a.where==='string'?a.where.trim():'';return w&&w!=="on the PC's GPU"?nounOf(w):noun()}
function Noun(){var n=noun();return n.charAt(0).toUpperCase()+n.slice(1)}
function whereWords(w){return w==="on the PC's GPU"?"on the "+noun()+"'s GPU":w}
var pane=new URLSearchParams(location.search).get('pane');
if(pane!=='phone'&&pane!=='gpu')pane=null;
if(pane){document.documentElement.setAttribute('data-pane',pane);G(pane==='phone'?'thumb':'list').hidden=true}
if(pane==='gpu'){
 G('thumb').insertBefore(G('controls'),G('gpu-pane'));
 G('thumb').insertBefore(G('ai-title'),G('controls'));
}
if(pane==='phone')G('list').appendChild(G('home').parentNode);
var token=document.querySelector('meta[name=opos-token]').content;
var stale=false;
var boot=null,rev=-1,current=null,timer=null,busy=false,queue=[],last=-Infinity,open=false,pendingCode=null,presetKey=null;
var OPEN=['queued','waiting','loading','answering','paused'];
var ERRORS={no_model:'No model is available on this phone.',stream_error:'The phone model could not finish the answer.',
 too_long:'The answer reached the storage limit.',restart:'The phone restarted before the answer finished.',
 worker_start:'The phone could not start the answer.',storage_error:'The phone could not save the answer.',
 low_memory:'Not enough free memory for this model right now.',model_start:'This model could not start.'};
var PHONE_ONLY=['no_model','stream_error','restart','worker_start','storage_error','low_memory','model_start'];
function errorWords(name,code){
 if(name==='gpu'&&PHONE_ONLY.indexOf(code)>=0)return '';
 return Object.prototype.hasOwnProperty.call(ERRORS,code)?ERRORS[code]:'';
}
function linkWords(link){
 if(!link)return 'GPU Link is off.';
 if(!link.pc)return link.enrol==='closed'?'Computer requests are closed.':'Waiting for the computer';
 if(link.pc.main_live===false||!link.pc.live)return 'Waiting for the '+noun();
 if(link.pc.state==='error')return 'The '+noun()+' could not run the model.';
 if(link.pc.state==='copying')return 'Copying the model';
 if(link.pc.state==='loading')return 'Loading the model';
 if(link.pc.state==='stopping')return 'Stopping';
 if(link.pc.state==='idle')return 'The '+noun()+' is not ready yet.';
 if(link.pc.state==='busy')return 'The '+noun()+' is busy.';
 if(link.model.state==='checking')return 'Checking the model file';
 if(link.model.state==='error')return 'The model file could not be read.';
 if(link.model.state==='none')return 'No GPU model file is available.';
 return 'Ready';
}
function storageWords(link){return link.storage_notice||ERRORS.storage_error}
function words(name,p){
 if(name==='gpu'&&p.link&&p.link.storage==='error')return storageWords(p.link);
 var a=p.answer;
 if(a){
  if(a.state==='failed')return errorWords(name,a.error)||(name==='gpu'?'The '+answerNoun(a)+' could not finish the answer.':'The phone could not finish the answer.');
  if(a.state==='done')return a.finish==='length'?'Done: the model reached its answer limit.':'Done';
  if(a.state==='cancelled')return 'Stopped';
  if(a.state==='paused')return name==='gpu'?'Paused. It continues when the '+answerNoun(a)+' is ready.':'Paused';
  if(a.state==='queued')return 'Queued behind an earlier answer';
  if(a.state==='loading')return 'Loading the model';
  if(a.state==='answering')return 'Answering';
  if(name==='phone')return 'Waiting for the phone model';
  if(name!=='gpu')return 'Waiting for its turn';
  return linkWords(p.link)==='Ready'?'Waiting for the '+noun():linkWords(p.link);
 }
 return name==='gpu'?linkWords(p.link):(p.ready?'Ready':'No model is available on this phone.');
}
function cableState(p){
 var pc=p.link&&p.link.pc;
 if(!pc)return '';
 if(!pc.live)return 'out';
 return p.link.storage_fault||pc.state==='copying'?'wait':'ok';
}
function cableWords(p){
 var state=cableState(p),a=p.answer,pc=p.link&&p.link.pc,open=!!(a&&OPEN.indexOf(a.state)>=0);
 if(p.link&&p.link.storage_fault)return storageWords(p.link)+(state==='wait'?' Wait before unplugging.':'');
 var stuck=!!pc&&(pc.state==='stopping'||pc.state==='error');
 if(state==='')return '';
 if(state==='out'){
  if(!open)return 'Not connected. Check the cable and the '+noun()+'.';
  return stuck?'Not connected. The answer is saved.':'Not connected. The answer is saved and continues when the '+noun()+' is ready again.';
 }
 if(state==='wait')return 'Copying the model to the '+noun()+'. Wait before unplugging.';
 if(!open)return 'Connected. Safe to unplug.';
 if(stuck)return 'Connected. Safe to unplug: the answer is saved.';
 return 'Connected. Safe to unplug: the answer is saved and continues when the '+noun()+' is ready again.';
}
function drawPane(name,p){
 var off=name==='gpu'&&!p.link,a=off?null:p.answer,isOpen=!!(a&&OPEN.indexOf(a.state)>=0);
 var pc=name==='gpu'&&p.link&&p.link.pc;
 var final=!!a&&['done','failed','cancelled'].indexOf(a.state)>=0;
 var here=pc&&(!a||(a.where?a.where===pc.label:!final));
 var where=here?[pc.label,pc.gpu&&pc.gpu.name].filter(Boolean).join(' · '):whereWords(p.where);
 line(name+'-model',off?'':[p.model,where].filter(Boolean).join(' · '));
 var state=off?'GPU Link is off.':words(name,p);
 if(pc&&pc.state==='copying'&&pc.total>0&&pc.copied!=null&&state==='Copying the model')
  state+=': '+Math.min(100,Math.floor(pc.copied*100/pc.total))+'%';
 var speed=a&&a.tps!=null;
 var live=name==='phone'&&a&&a.state==='answering'&&p.live_speed!=null&&!speed;
 text(name+'-speed',speed?a.tps+' tokens per second':live?'about '+p.live_speed+' pieces per second':state);
 line(name+'-state',[speed||live?state:'',a&&a.tokens!=null?a.tokens+' tokens':''].filter(Boolean).join(' · '));
 if(name==='gpu'){G('gpu-disclosure').hidden=off;line('gpu-cable',cableWords(p));G('gpu-cable').dataset.cable=cableState(p)}
 var box=G(name+'-answer'),value=a?a.text:'',follow=box.scrollHeight-box.clientHeight-box.scrollTop<=24;
 var changed=box.dataset.answer!==(a?a.id:'');
 if(changed){follow=true;box.dataset.answer=a?a.id:''}
 if(box.textContent!==value){box.textContent=value;if(follow)box.scrollTop=box.scrollHeight}
 else if(changed)box.scrollTop=box.scrollHeight;
 box.hidden=off;
 G(name+'-pane').dataset.open=String(isOpen);G(name+'-pane').dataset.state=a?a.state:'idle';
 G(name+'-stop').hidden=!isOpen;
 G(name+'-stop').onclick=function(){send({action:'cancel',id:a.id})};
}
function drawPCModels(s){
 var root=G('pc-extra'),items=(s.models||[]).filter(function(m){return m.kind==='pc'&&/^g[1-3]$/.test(m.pane)||m.kind==='phone'&&/^m[1-4]$/.test(m.pane)});
 var keep=items.map(function(m){return m.pane});
 Array.from(root.children).forEach(function(e){if(keep.indexOf(e.dataset.pane)<0)e.remove()});
 items.forEach(function(m){
  var id=m.pane,card=G(id+'-pane');
  if(!card){
   card=document.createElement('section');card.id=id+'-pane';card.className='pane';card.dataset.pane=id;
   [['h2','title'],['p','model'],['p','speed'],['p','state'],['div','answer'],['button','stop']].forEach(function(pair){
    var e=document.createElement(pair[0]);e.id=id+'-'+pair[1];
    if(pair[1]==='answer'){e.className='answer';e.tabIndex=0;e.setAttribute('role','region');e.setAttribute('aria-label',id+' answer')}
    if(pair[1]==='stop'){e.className='stop';e.type='button';e.textContent='Stop '+id+' answer'}
    card.appendChild(e)});
   root.appendChild(card);
  }
  var a=m.answer,open=!!(a&&OPEN.indexOf(a.state)>=0),state='Waiting for the '+noun();
  if(a){
   if(a.state==='failed')state=m.kind==='pc'?'The '+answerNoun(a)+' could not finish the answer.':'The phone model could not finish the answer.';
   else if(a.state==='done')state=a.finish==='length'?'Done: the model reached its answer limit.':'Done';
   else if(a.state==='cancelled')state='Stopped';
   else if(a.state==='paused')state=m.kind==='pc'?'Paused. It continues when the '+answerNoun(a)+' is ready.':'Paused';
   else if(a.state==='queued')state='Queued behind an earlier answer';
   else if(a.state==='loading')state=m.kind==='pc'?'Warming model':'Loading the model';
   else if(a.state==='answering')state='Answering';
  }else if(m.ready)state='Ready';
  if(!a&&!m.ready&&m.kind==='phone')state='No model is available on this phone.';
  text(id+'-title',m.label||id);text(id+'-model',[m.model,m.maker,whereWords(m.where)].filter(Boolean).join(' · '));
  text(id+'-speed',a&&a.tps!=null?a.tps+' tokens per second':m.live_speed!=null&&a&&a.state==='answering'?m.live_speed+' tokens per second':state);
  line(id+'-state',a&&a.tps!=null?state:'');
  var box=G(id+'-answer'),value=a?a.text:'';
  if(box.textContent!==value){var follow=box.scrollHeight-box.clientHeight-box.scrollTop<=24;box.textContent=value;if(follow)box.scrollTop=box.scrollHeight}
  card.dataset.state=a?a.state:'idle';card.dataset.open=String(open);
  G(id+'-stop').hidden=!open;G(id+'-stop').onclick=function(){if(a)send({action:'cancel',id:a.id})};
 });
}
function line(id,value){text(id,value);G(id).hidden=!value}
function targets(){
 var base=pane==='phone'?['phone']:pane==='gpu'?['gpu']:['phone','gpu'];
 if(current)base=base.concat((current.models||[]).filter(function(m){return m.ready&&
  (pane===null||pane==='gpu'&&m.kind==='pc'||pane==='phone'&&m.kind==='phone')}).map(function(m){return m.pane}));
 return base.filter(function(n){return n!=='gpu'||current&&current.gpu.link});
}
function answering(){
 if(!current)return false;
 return targets().some(function(n){var p=current[n]||(current.models||[]).find(function(m){return m.pane===n}),a=p&&p.answer;return a&&OPEN.indexOf(a.state)>=0});
}
function noticeStands(){return targets().indexOf('gpu')>=0&&!!current.gpu.link.storage_notice}
function askingBusy(){return answering()||noticeStands()}
function buttons(){
 var disabled=!current||!targets().length||askingBusy();G('ask').disabled=disabled;
 text('ask',pane==='gpu'?'Ask '+noun()+' GPU models':pane==='phone'||!current.gpu.link?'Ask the phone model':'Ask all ready models');
 Array.from(G('presets').children).forEach(function(b){b.disabled=disabled});
}
function draw(s){
 if(s.locked){current=null;open=false;G('controls').hidden=true;G('enrol').hidden=true;
  ['phone','gpu'].forEach(function(n){text(n+'-answer','');line(n+'-state','');
   line(n+'-model','');text(n+'-speed','Unlock the phone to use AI mode.');G(n+'-stop').hidden=true});
  G('pc-extra').textContent='';document.documentElement.setAttribute('data-fanout','false');text('enrol-text','');line('gpu-cable','');
  G('allow').hidden=true;G('forget').hidden=true;G('reopen').hidden=true;return;
 }
 if(!s.phone||!s.gpu)return;
 if(s.boot===boot&&s.rev<rev)return;
 boot=s.boot;rev=s.rev;current=s;G('controls').hidden=false;G('allow').hidden=false;
 document.documentElement.setAttribute('data-fanout',String((s.models||[]).some(function(m){return m.kind==='pc'})));
 // Every field is drawn synchronously from s; the browser paints after this task.
 drawPane('phone',s.phone);drawPane('gpu',s.gpu);
 drawPCModels(s);
 open=[s.phone,s.gpu].concat(s.models||[]).some(function(p){return p.answer&&OPEN.indexOf(p.answer.state)>=0});
 var link=s.gpu.link,pc=link&&link.pc,pending=link&&link.pending;
 G('enrol').hidden=!pending;G('reopen').hidden=!(link&&link.enrol==='closed');G('forget').hidden=!pc;
 text('enrol-text',pending?'Use the GPU of '+pending.label+'? Code '+pending.code.slice(0,3)+' '+pending.code.slice(3)+
  '. This '+nounOf(pending.label)+' will see what you ask in AI mode and will keep a copy of the model file.':'');
 text('gpu-title',Noun()+' GPU');text('gpu-disclosure','This '+noun()+' can see what you ask here.');
 G('gpu-answer').setAttribute('aria-label',Noun()+' GPU answer');
 text('forget','Forget this '+noun());
 var nextCode=pending?pending.code:null,active=document.activeElement;
 if(nextCode&&nextCode!==pendingCode&&!G('thumb').hidden&&!(active&&/^(INPUT|TEXTAREA)$/.test(active.tagName)))
  G('deny').focus({preventScroll:true});
 pendingCode=nextCode;
 var key=JSON.stringify(s.presets);if(key!==presetKey){presetKey=key;
  var presets=G('presets');presets.textContent='';
  s.presets.forEach(function(q){var b=document.createElement('button');b.type='button';b.textContent=q.label;
   b.onclick=function(){if(b.disabled)return;G('question').value=q.question;ask()};presets.appendChild(b)});
 }
 buttons();
}
function interval(){return open?100:2000}
function schedule(){
 clearTimeout(timer);timer=null;
 if(document.hidden||busy||stale)return;
 timer=setTimeout(request,Math.max(0,last+interval()-performance.now()));
}
function request(){
 timer=null;if(document.hidden||busy)return;
 busy=true;last=performance.now();var body=queue.shift();
 var controller=new AbortController(),timeout,timedOut=false;
 var deadline=new Promise(function(resolve,reject){timeout=setTimeout(function(){
  timedOut=true;controller.abort();reject(new Error('timeout'));
 },10000)});
 var response=Promise.resolve().then(function(){return fetch('/api/ai',{
  method:body?'POST':'GET',headers:Object.assign({'X-OPOS-Token':token},body?{'Content-Type':'application/json'}:{}),
  body:body?JSON.stringify(body):undefined,signal:controller.signal});
 }).then(function(r){return r.json().then(function(s){return {status:r.status,snapshot:s}})});
 Promise.race([response,deadline]).then(function(result){
   var r=result,s=result.snapshot;
   if(r.status===403&&s&&s.error==='forbidden'){
    stale=true;text('err','This page is out of date. Reload it, then try again.');return}
   if(r.status===403&&s&&s.error==='locked'){queue=[];draw({locked:true})}
   if(r.status!==200){text('err',s.error||'AI mode could not update.');return}
   text('err','');draw(s);
  }).catch(function(){text('err',timedOut?'The phone did not answer.':'AI mode could not update.');
  }).finally(function(){clearTimeout(timeout);busy=false;schedule()});
}
function send(body){if(document.hidden)return;queue.push(body);schedule()}
function ask(){
 if(!current||!targets().length)return;
 if(answering()){text('err','Wait for this answer, or stop it.');return}
 if(noticeStands()){text('err',current.gpu.link.storage_notice);return}
 send({action:'ask',question:G('question').value,panes:targets()});
}
G('ask').onclick=ask;
G('question').onkeydown=function(e){if(e.key==='Enter'){e.preventDefault();ask()}};
['allow','deny'].forEach(function(action){G(action).onclick=function(){send({action:action,code:pendingCode})}});
['reopen','forget'].forEach(function(action){G(action).onclick=function(){send({action:action})}});
document.addEventListener('visibilitychange',schedule);
schedule();
"""


def render(token: str, nonce: str) -> str:
    """Build a separate app document without changing the home page."""
    return appdoc.render("AI mode", token, nonce, _LIST, _THUMB, _SCRIPT, _CSS)


APP = apps.register(
    apps.App(
        "ai",
        "AI mode",
        "/ai",
        DISCLOSURE,
        "yes, with a local model",
        "questions to the paired computer when the GPU pane is used",
        "phone model and optional computer GPU",
        "real",
        "ai",
        "OPTIONAL",
        0,
        render,
        snapshot,
        post,
    )
)

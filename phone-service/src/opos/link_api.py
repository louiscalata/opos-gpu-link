# SPDX-License-Identifier: Apache-2.0
"""The loopback API the OPOS GPU Link Android app reads: GET /ai, GET and POST /api/ai.

This is the GPU Link part of the phone service on its own. It serves:

- ``GET /ai``: a tiny page whose ``<meta name="opos-token">`` carries the session token.
- ``GET /api/ai``: the snapshot of the phone, GPU and extra computer lanes (``X-OPOS-Token`` required).
- ``POST /api/ai``: ``ask``, ``cancel``, ``retry``, ``allow``, ``deny``, ``reopen`` and ``forget``
  (JSON body, loopback ``Origin``, ``X-OPOS-Token``).

Computer lanes are answered by the GPU Link listener in ``gpu_link_server``. The phone lane is optional: pass
an OpenAI-compatible chat-completions server on this phone's loopback (for example llama.cpp's
``llama-server``) and its answers stream into the same store; without one the phone lane reports
not ready and asks go to the computer lanes only.
"""

from __future__ import annotations

import http.client
import json
import secrets
import socket
import threading
import time
import urllib.parse
from collections.abc import Callable
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from opos import ai_answers, gpu_link_server, secure
from opos.gpu_link import answer_noun, computer_title, display_label, display_model_name

APPEND_INTERVAL = 0.25
BODY_LIMIT = 6 * ai_answers.MAX_QUESTION_BYTES + 256
MAX_LINE = 65536  # one SSE line from the phone model server
MAX_CONNECTIONS = 16
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
    for label, question in zip(("Why the sky is blue", "A welcoming garden", "A long guide (20 sections)"), QUESTIONS)
)
POOL_PANES = tuple(pane for pane in ai_answers.PANES if pane != "phone" and pane not in ai_answers.PC_PANES)
LINK_ACTIONS = ("allow", "deny", "reopen", "forget")


def _shown_answer(answer: dict | None) -> dict | None:
    """Map a saved model name for display, without writing to the answer store."""
    if not answer:
        return answer
    name = display_model_name(answer.get("model"))
    return answer if name == answer.get("model") else {**answer, "model": name}


def _link() -> Any:
    return gpu_link_server.service()


class NoModel(Exception):
    """The phone model server could not be reached."""


class StreamError(Exception):
    """The phone model server answered with something other than a complete stream."""


class PhoneModel:
    """An OpenAI-compatible chat server on this phone's loopback."""

    def __init__(self, base_url: str, model: str, label: str = "") -> None:
        bad = ValueError("the phone model URL must be http://127.0.0.1:PORT/v1")
        if not isinstance(base_url, str) or "?" in base_url or "#" in base_url or "@" in base_url:
            raise bad
        parts = urllib.parse.urlsplit(base_url.rstrip("/"))
        try:
            port = parts.port
        except ValueError:
            raise bad from None
        if parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost") or not port:
            raise bad
        if not isinstance(model, str) or not model.strip() or len(model) > 200:
            raise ValueError("name the phone model")
        self.host, self.port = "127.0.0.1", port
        self.path = (parts.path or "") + "/chat/completions"
        self.url = f"http://127.0.0.1:{port}{self.path}"
        self.model = model.strip()
        self.label = (label or self.model)[:64]

    def stream(self, question: str, call: "PhoneCall", timeout: float = 120.0):
        """Yield text pieces from a streamed chat completion and return its finish reason.

        Raises NoModel when the server cannot be reached, StreamError for anything but a
        complete event stream. ``call`` holds the connection so a cancel can close it.
        """
        body = json.dumps({"model": self.model, "stream": True, "max_tokens": 4096,
                           "messages": [{"role": "user", "content": question}]}).encode("utf-8")
        connection = http.client.HTTPConnection(self.host, self.port, timeout=timeout)
        call.attach(connection)
        try:
            try:
                connection.request("POST", self.path, body, {"Content-Type": "application/json",
                                                             "Accept": "text/event-stream"})
                response = connection.getresponse()
            except (ConnectionError, socket.timeout, TimeoutError, OSError) as err:
                if call.cancelled.is_set():
                    return "cancelled"
                raise NoModel() from err
            if response.status != 200 or response.headers.get_content_type() != "text/event-stream":
                raise StreamError()
            finish = None
            while True:
                raw = response.readline(MAX_LINE + 1)
                if call.cancelled.is_set():
                    return "cancelled"
                if not raw:
                    break
                if len(raw) > MAX_LINE:
                    raise StreamError()
                line = raw.decode("utf-8", errors="replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return finish or "stop"
                try:
                    choice = json.loads(data)["choices"][0]
                    delta = choice.get("delta") or {}
                    piece = delta.get("content") if isinstance(delta, dict) else None
                    reason = choice.get("finish_reason")
                except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                    continue
                if isinstance(piece, str) and piece:
                    yield piece
                if reason is not None:
                    finish = "length" if reason == "length" else "stop"
            if call.cancelled.is_set():
                return "cancelled"
            if finish is None:
                raise StreamError()  # the server stopped before saying it was done
            return finish
        except (ConnectionError, socket.timeout, TimeoutError, http.client.HTTPException, OSError) as err:
            if call.cancelled.is_set():
                return "cancelled"
            raise StreamError() from err
        finally:
            call.detach()
            connection.close()


class PhoneCall:
    """The cancel flag and open connection of one phone answer."""

    def __init__(self) -> None:
        self.cancelled = threading.Event()
        self._lock = threading.Lock()
        self._connection: http.client.HTTPConnection | None = None

    def attach(self, connection: http.client.HTTPConnection) -> None:
        with self._lock:
            self._connection = connection

    def detach(self) -> None:
        with self._lock:
            self._connection = None

    def cancel(self) -> None:
        """Stop the answer and wake a blocked read so the server stops generating."""
        self.cancelled.set()
        with self._lock:
            sock = self._connection.sock if self._connection is not None else None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass


class PhoneWorker:
    """Answer one phone-lane question in its own thread."""

    def __init__(self, answers: ai_answers.AnswerStore, ident: str, model: PhoneModel) -> None:
        self.answers, self.ident, self.model = answers, ident, model
        self.call = PhoneCall()
        self.cancelled = self.call.cancelled
        self.live_speed: int | None = None
        self.thread = threading.Thread(target=self._run, name="link-api-phone-" + ident, daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _wait_turn(self) -> bool:
        while not self.cancelled.is_set():
            answer = self.answers.get(self.ident)
            if answer is None or answer["state"] in ai_answers.FINAL:
                return False
            if answer["state"] == "waiting":
                return True
            self.cancelled.wait(0.05)
        return False

    def _run(self) -> None:
        code = None
        try:
            if not self._wait_turn():
                return
            answer = self.answers.begin(self.ident)
            self.answers.note(self.ident, model=self.model.label, where="on this phone")
            offset, pending, last, first, pieces = 0, b"", float("-inf"), None, 0
            stream = self.model.stream(answer["question"], self.call)
            finish = "stop"
            while True:
                try:
                    piece = next(stream)
                except StopIteration as stop:
                    finish = stop.value or "stop"
                    break
                if self.cancelled.is_set():
                    stream.close()
                    return
                now = time.monotonic()
                pieces += 1
                first = first or now
                if now - first >= 1:
                    self.live_speed = round(pieces / (now - first))
                pending += ai_answers.clean(piece).encode("utf-8")
                if offset + len(pending) > ai_answers.MAX_ANSWER_BYTES:
                    stream.close()
                    raise ai_answers.TooLongError(offset)
                if pending and now - last >= APPEND_INTERVAL:
                    self.answers.append(self.ident, offset, pending)
                    offset, pending, last = offset + len(pending), b"", now
            if self.cancelled.is_set():
                return
            self.answers.append(self.ident, offset, pending, done=True, finish=finish)
        except ai_answers.TooLongError:
            code = "too_long"
        except NoModel:
            code = "no_model"
        except StreamError:
            code = "stream_error"
        except OSError:
            code = "storage_error"
        except Exception:  # Thread boundary: store a safe code, never raw error text.
            code = "stream_error"
        finally:
            self.live_speed = None
            answer = self.answers.get(self.ident)
            if answer is not None and answer["state"] not in ai_answers.FINAL:
                try:
                    if self.cancelled.is_set():
                        self.answers.cancel(self.ident)
                    else:
                        self.answers.fail(self.ident, code or "stream_error")
                except (ai_answers.AnswerError, OSError):
                    pass


class LinkApi:
    """Serialize the app's actions and number complete snapshots."""

    def __init__(self, phone: PhoneModel | None = None,
                 answers: Callable[[], ai_answers.AnswerStore] = ai_answers.shared,
                 link: Callable[[], Any] = _link) -> None:
        self.phone = phone
        self._answers = answers
        self._link = link
        self.lock = threading.RLock()
        self.boot = secrets.token_hex(4)
        self.rev = 0
        self._previous: dict | None = None
        self.workers: dict[str, PhoneWorker] = {}

    # ---- snapshot ----

    def _views(self, answers: ai_answers.AnswerStore, link: Any) -> tuple:
        # Retry overlapping writes so the phone and GPU answers come from one revision.
        for _ in range(20):
            before = link.snapshot() if link is not None else None
            revision = answers.rev
            lanes = {pane: answers.current(pane) or answers.latest(pane) for pane in ai_answers.PC_PANES + ("phone",)}
            after = link.snapshot() if link is not None else None
            if revision == answers.rev and before == after:
                return lanes, after, revision
        raise OSError("busy")

    def snapshot(self) -> dict:
        with self.lock:
            self.workers = {key: job for key, job in self.workers.items() if job.thread.is_alive()}
            lanes, link, revision = self._views(self._answers(), self._link())
            phone, gpu = lanes["phone"], lanes["gpu"]
            extra = {pane: lanes[pane] for pane in ai_answers.PC_PANES[1:]}
            pc = link["pc"] if link is not None else None
            gpu_model = link["model"] if link is not None else None
            lead_label = (pc or {}).get("lead_label")
            same_pc = bool(pc and (not gpu or (gpu["state"] not in ai_answers.FINAL
                                               and (not gpu["where"] or display_label(gpu["where"]) == pc["label"]))))
            pc_models = list((pc or {}).get("models") or [])
            shown = {item.get("pane") for item in pc_models}
            pc_models.extend({"pane": pane, "id": "", "label": display_model_name(answer["model"]) or f"{computer_title(answer_noun(answer.get('where'), (pc or {}).get('label')))} {pane}",
                              "maker": "",
                              "live": False, "live_speed": None}
                             for pane, answer in extra.items() if answer is not None and pane not in shown)
            storage = bool(link and link.get("storage_notice"))
            phone_job = self.workers.get(phone["id"]) if phone else None
            body = {
                "phone": {
                    "model": display_model_name((phone["model"] if phone else "") or (self.phone.label if self.phone else "")),
                    "where": (phone["where"] if phone else "") or "on this phone",
                    "ready": self.phone is not None and not (phone and phone["error"] == "no_model"),
                    "answer": _shown_answer(phone),
                    "live_speed": phone_job.live_speed if phone_job and phone["state"] == "answering" else None,
                },
                "gpu": {
                    **({"lead_label": lead_label} if lead_label is not None else {}),
                    "model": display_model_name((lead_label if same_pc else None) or (gpu["model"] if gpu else "")
                    or (gpu_model["name"] if gpu_model else "")),
                    "where": (gpu["where"] if gpu else "") or "on the PC's GPU",
                    "ready": bool(gpu_model and gpu_model["state"] == "ready" and pc and pc["live"]
                                  and pc.get("main_live", pc["live"]) and pc["state"] == "ready" and not storage),
                    "answer": _shown_answer(gpu),
                    "link": link,
                },
                "models": [
                    {
                        "pane": item["pane"], "kind": "pc", "label": item["label"], "maker": item["maker"],
                        "model": display_model_name((extra[item["pane"]]["model"] if extra[item["pane"]] else "") or item["label"]),
                        "where": "on the PC's GPU",
                        "ready": bool(pc and pc["live"] and item["live"] and not storage),
                        "answer": _shown_answer(extra[item["pane"]]),
                        "live_speed": item.get("live_speed")
                        if extra[item["pane"]] and extra[item["pane"]]["state"] == "answering" else None,
                    }
                    for item in pc_models if item.get("pane") in extra
                ],
                "presets": deepcopy(list(PRESETS)),
            }
            comparison = {"store_rev": revision, **body}
            if comparison != self._previous:
                self.rev += 1
                self._previous = deepcopy(comparison)
            return {"boot": self.boot, "rev": self.rev, **body}

    # ---- actions ----

    def _chosen(self, panes: Any) -> list[str]:
        # The app may still send m1-m4 (phone model-pool lanes of the full OPOS host); this
        # service has no model pool, so those lanes are simply not available here.
        if not isinstance(panes, list) or not panes or any(pane not in ai_answers.PANES for pane in panes):
            raise ValueError("Choose an available phone, GPU, or model pane.")
        if len(set(panes)) != len(panes):
            raise ValueError("Choose each pane once.")
        link = self._link()
        advertised = ({item["pane"] for item in ((link.snapshot().get("pc") or {}).get("models") or [])
                       if item.get("id")} if link is not None else set())
        chosen = [pane for pane in panes
                  if (pane != "phone" or self.phone is not None)
                  and (pane != "gpu" or link is not None)
                  and (pane not in ai_answers.PC_PANES[1:] or pane in advertised)
                  and pane not in POOL_PANES]
        if not chosen:
            raise ValueError("GPU Link is off." if panes == ["gpu"] else "No selected model is available.")
        return chosen

    def ask(self, data: dict) -> None:
        question = data.get("question")
        if not isinstance(question, str) or not ai_answers.clean(question).strip():
            raise ValueError("Enter a question.")
        question = ai_answers.clean(question)
        if len(question.encode("utf-8")) > ai_answers.MAX_QUESTION_BYTES:
            raise ValueError("Keep the question to 4,096 bytes or fewer.")
        panes = self._chosen(data.get("panes"))
        answers = self._answers()
        if any(pane in ai_answers.PC_PANES for pane in panes) and answers.startup_notice:
            raise ValueError(answers.startup_notice)
        if any(answers.current(pane) is not None for pane in panes):
            raise ValueError("Wait for this answer, or stop it.")
        unfinished = sum(row["state"] not in ai_answers.FINAL for row in answers.snapshot()["answers"])
        if unfinished + len(panes) > ai_answers.MAX_ANSWERS:
            raise ai_answers.FullError("full")
        stored = []
        try:
            for pane in panes:
                stored.append(answers.ask(pane, question))
        except Exception:
            for answer in stored:
                try:
                    answers.fail(answer["id"], "storage_error")
                except (ai_answers.StateError, OSError):
                    pass
            raise
        for answer in stored:
            if answer["pane"] == "phone" and self.phone is not None:
                job = PhoneWorker(answers, answer["id"], self.phone)
                self.workers[job.ident] = job
                try:
                    job.start()
                except RuntimeError:
                    del self.workers[job.ident]
                    answers.fail(job.ident, "worker_start")

    def cancel(self, ident: Any) -> None:
        """Stop one answer. Unknown ids are refused so a stale tap cannot hide a miss."""
        self.cancel_many([ident], missing="error")

    def cancel_many(self, idents: list[str], *, missing: str = "skip") -> None:
        """Set every targeted cancel flag, then tear down. Already-ended answers are skipped."""
        if missing not in ("error", "skip"):
            raise ValueError("missing must be error or skip")
        answers = self._answers()
        items: list[tuple[str, dict, object | None]] = []
        seen: set[str] = set()
        for ident in idents:
            if not isinstance(ident, str) or not ident:
                if missing == "error":
                    raise ValueError("That answer was not found.")
                continue
            if ident in seen:
                continue
            seen.add(ident)
            answer = answers.get(ident)
            if answer is None:
                if missing == "error":
                    raise ValueError("That answer was not found.")
                continue
            items.append((ident, answer, self.workers.get(ident)))
        if not items and missing == "error":
            raise ValueError("That answer was not found.")
        for _, _, job in items:
            if job is not None:
                job.call.cancel()
        link = self._link()
        first_error: BaseException | None = None
        for ident, answer, job in items:
            try:
                current = answers.get(ident) or answer
                if current["state"] in ai_answers.FINAL:
                    if missing == "error":
                        answers.cancel(ident)
                elif current["pane"] in ai_answers.PC_PANES and link is not None:
                    link.cancel(ident)
                else:
                    answers.cancel(ident)
            except ai_answers.StateError:
                if missing == "error":
                    raise
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def retry(self, data: dict) -> None:
        pane = data.get("pane")
        if not isinstance(pane, str) or pane not in ai_answers.PANES:
            raise ValueError("Choose a model to retry.")
        answers = self._answers()
        latest = answers.current(pane) or answers.latest(pane)
        if latest is None:
            raise ValueError("There is no answer to retry.")
        expect = data.get("id")
        if expect is not None and expect != latest["id"]:
            raise ValueError("That answer has already been replaced.")
        if expect is None and latest["state"] not in ai_answers.FINAL:
            raise ValueError("Name the answer to retry.")
        if not latest["question"].strip():
            raise ValueError("There is no question to retry.")
        # Refuse before ending the old answer, so a refused Retry leaves it as it was.
        self._chosen([pane])
        if pane in ai_answers.PC_PANES and answers.startup_notice:
            raise ValueError(answers.startup_notice)
        if latest["state"] not in ai_answers.FINAL:
            try:
                self.cancel(latest["id"])
            except ai_answers.StateError:
                pass  # it finished meanwhile; ask again all the same
        self.ask({"question": latest["question"], "panes": [pane]})

    def link_action(self, action: str, data: dict) -> None:
        link = self._link()
        if link is None:
            raise ValueError("GPU Link is off.")
        if action in ("allow", "deny"):
            if getattr(link, action)(data.get("code")) is False:
                raise ValueError("That request is no longer waiting.")
        elif action == "forget":
            if link.forget(data.get("expect")) is False:
                raise ValueError("There is no computer request to change." if link.snapshot()["pc"] is None
                                 else "That is a different computer now.")
        elif link.reopen() is False:
            raise ValueError("There is no computer request to change.")

    def post(self, data: Any) -> tuple[int, dict]:
        """Apply one action and return a fresh snapshot, or a short refusal sentence."""
        if not isinstance(data, dict):
            return 400, {"error": "Choose an AI mode action."}
        with self.lock:
            try:
                action = data.get("action")
                if action == "ask":
                    self.ask(data)
                elif action == "cancel":
                    ids = data.get("ids")
                    if ids is None:
                        self.cancel(data.get("id"))
                    elif isinstance(ids, list) and ids and all(isinstance(item, str) and item for item in ids):
                        self.cancel_many(ids)
                    else:
                        raise ValueError("Choose which answers to stop.")
                elif action == "retry":
                    self.retry(data)
                elif action in LINK_ACTIONS:
                    self.link_action(action, data)
                else:
                    raise ValueError("Choose an AI mode action.")
                return 200, self.snapshot()
            except ai_answers.FullError:
                return 400, {"error": "Stop an unfinished answer before asking again."}
            except ai_answers.StateError:
                return 400, {"error": "That answer has already ended."}
            except OSError:
                return 500, {"error": "The phone could not save the answer."}
            except ValueError as err:
                return 400, {"error": str(err)}

    def close(self, timeout: float = 5.0) -> None:
        with self.lock:
            jobs = list(self.workers.values())
            for job in jobs:
                job.call.cancel()
        for job in jobs:
            if job.thread.ident is not None:
                job.thread.join(timeout)
        with self.lock:
            self.workers.clear()


# ---- HTTP ----

_PAGE = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
         '<meta name="opos-token" content="{token}"><title>OPOS GPU Link</title></head>'
         '<body><p>OPOS GPU Link phone service. Open the OPOS GPU Link app.</p></body></html>')


class _Handler(BaseHTTPRequestHandler):
    server: "AppServer"
    protocol_version = "HTTP/1.1"
    timeout = 10  # idle keep-alive connections do not hold a thread for long
    server_version = "OPOS-GPU-Link"
    sys_version = ""

    def log_message(self, format: str, *args: Any) -> None:  # questions never reach the log
        pass

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        for key, value in secure.security_headers().items():
            self.send_header(key, value)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if self.close_connection:
            self.send_header("Connection", "close")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, data: dict) -> None:
        self._send(status, json.dumps(data, separators=(",", ":")).encode("utf-8"), "application/json")

    def _path(self) -> str:
        return urllib.parse.urlsplit(self.path).path

    def _one(self, name: str) -> str | None:
        """Return a header that appears at most once; a repeated one counts as missing-and-wrong."""
        found = self.headers.get_all(name) or []
        if len(found) > 1:
            raise _Repeated()
        return found[0] if found else None

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        # Malformed or unknown requests get the same hardened JSON reply and a closed connection.
        self.close_connection = True
        try:
            self._json(code, {"error": "bad request" if code < 500 else "not supported"})
        except OSError:
            pass

    def handle_one_request(self) -> None:
        try:
            super().handle_one_request()
        except _Repeated:
            self.close_connection = True
            self._json(400, {"error": "bad request"})

    def do_GET(self) -> None:
        if self.headers.get("Content-Length") is not None or self.headers.get("Transfer-Encoding") is not None:
            self.close_connection = True  # never leave a body to be read as the next request
            self._json(400, {"error": "bad request"})
            return
        if not secure.host_ok(self._one("Host"), self.server.port):
            self._json(403, {"error": "forbidden"})
            return
        path = self._path()
        if path == "/ai":
            self._send(200, _PAGE.format(token=self.server.token).encode("utf-8"), "text/html; charset=utf-8")
        elif path == "/api/ai":
            if not secure.token_ok(self._one("X-OPOS-Token"), self.server.token):
                self._json(403, {"error": "forbidden"})
                return
            try:
                self._json(200, self.server.api.snapshot())
            except OSError:
                self._json(500, {"error": "The phone could not read the answers."})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        # Any refusal before the body is read must close the connection, or the unread
        # body would be parsed as the next request on this keep-alive connection.
        keep = not self.close_connection
        self.close_connection = True
        if self._path() != "/api/ai":
            self._json(404, {"error": "not found"})
            return
        if not secure.host_ok(self._one("Host"), self.server.port) \
                or not secure.origin_ok(self._one("Origin"), self.server.port):
            self._json(403, {"error": "forbidden"})
            return
        if not secure.json_type_ok(self._one("Content-Type")):
            self._json(415, {"error": "unsupported media type"})
            return
        if not secure.token_ok(self._one("X-OPOS-Token"), self.server.token):
            self._json(403, {"error": "forbidden"})
            return
        try:
            data = secure.read_json_body(self.rfile, self.headers, BODY_LIMIT)
        except secure.BodyError as err:
            self._json(err.status, {"error": err.message})
            return
        self.close_connection = not keep
        status, reply = self.server.api.post(data)
        self._json(status, reply)

    def _refuse(self) -> None:
        self.close_connection = True
        self._json(405, {"error": "method not allowed"})

    do_HEAD = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_TRACE = do_CONNECT = _refuse


class _Repeated(Exception):
    """A security header appeared more than once."""


class AppServer(ThreadingHTTPServer):
    """Loopback-only HTTP server for the app API."""

    daemon_threads = True

    def __init__(self, api: LinkApi, host: str = "127.0.0.1", port: int = 8765) -> None:
        secure.check_bind(host)
        if host != "127.0.0.1":
            raise ValueError("IPv4 loopback only")
        super().__init__((host, port), _Handler)
        self.api = api
        self.token = secure.new_token()
        self.port = self.server_address[1]
        self._thread: threading.Thread | None = None
        self._slots = threading.BoundedSemaphore(MAX_CONNECTIONS)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._slots.acquire(blocking=False):
            self.shutdown_request(request)  # too many open connections: drop this one
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # a dropped client connection is not worth a traceback, and requests stay out of logs

    def start(self) -> None:
        self._thread = threading.Thread(target=self.serve_forever, name="link-api-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            self.shutdown()
        self.server_close()
        if self._thread is not None:
            self._thread.join(5)
        self.api.close()

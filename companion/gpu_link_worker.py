#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Play the computer side of GPU Link through an existing loopback port forward.

Enrol through the owner's developer command, then approve the code on the phone:
  python3 -B tools/gpu-link-standin-pc.py --key-file ./pc.key --enrol-request | <phone enrolment command>
The command is adb shell running nc to the phone's loopback link port, or ssh
with strict host-key checking running the same. Then run practice mode:
  python3 -B tools/gpu-link-standin-pc.py --key-file ./pc.key
Existing chat-completions server example:
  python3 -B tools/gpu-link-standin-pc.py --key-file ./pc.key --text server \
    --server http://127.0.0.1:8080/v1/chat/completions --model local-model

Developer tool only. Enrolment writes one HTTP request to a pipe and never opens
a connection. The key travels only on the developer command's standard input.
No window, permission grant, forward creation, model download or engine startup.
Practice text is simulated; no speed or GPU hardware is claimed. Server
resume includes the stored partial as an assistant message; continuation quality
and prefix support depend on the server. Token counts fall back to word estimates.
Use the full endpoint URL. HTTP and HTTPS loopback literals or localhost only;
no proxies, redirects or compressed replies. Keys are raw 32-byte mode-0600 files.
Questions and answers stay out of event lines unless --show-text is supplied.
Ctrl-C stops the tool and closes its current stream. Physical phone checks remain
NOT_RUN. The lead lane needs a ready phone model file; extra computer model lanes use
their advertised model IDs through the same signed link.
"""

from __future__ import annotations

import argparse
import errno
import http.client
import io
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import stat
import sys
import threading
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from opos import gpu_link_proto as proto

try:
    from gpu_link_guard import GuardState
except ImportError:  # Keep older partial companion copies usable during integration.
    GuardState = None
try:
    import gpu_link_salad
except ImportError:  # optional word-salad judge
    gpu_link_salad = None

GUARD_RETRY_TEMPERATURE = 0.4
GUARD_RETRY_REPEAT_PENALTY = 1.1
GUARD_RETRY_TOP_P = 0.9
SYSTEM_PROMPT_ENV = "OPOS_GPU_LINK_SYSTEM_PROMPT"
SYSTEM_PROMPT_PATH = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "demo_system_prompt.txt"


def default_system_message(messages: list[dict[str, str]]) -> list[dict[str, str]]:
    """Add the local demo instruction without changing phone work messages."""
    if os.environ.get(SYSTEM_PROMPT_ENV, "1") == "0" or any(
        message.get("role") == "system" for message in messages
    ):
        return messages
    try:
        prompt = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
    except OSError:
        raise ToolError("demo system prompt is unavailable") from None
    if not prompt:
        raise ToolError("demo system prompt is empty")
    return [{"role": "system", "content": prompt}, *messages]


class GuardRetryBudget:
    """One retry for the current lane lease, retained across transport resumes."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.key = None
        self.used = False
        self.seed = None

    def begin(self, job: dict) -> tuple[int, bool]:
        with self.lock:
            key = (job.get("lease"), job["question"])
            if key != self.key:
                self.key, self.used = key, False
            return self._seed(), self.used

    def _seed(self) -> int:
        previous = self.seed
        self.seed = secrets.randbelow(2**31)
        if self.seed == previous:
            self.seed = (self.seed + 1) % (2**31)
        return self.seed

    def retry(self) -> int | None:
        with self.lock:
            if self.used:
                return None
            self.used = True
            return self._seed()


PRACTICE = (
    "Practice text from a stand-in computer. This is simulated text, with no model or GPU work.\n"
    + "A shared library starts with a room, a shelf and a list. Neighbours bring things and borrow them.\n" * 8
)
ENROL_REFUSED = "Enrolment request refused: stdout must be a pipe or socket to the phone enrolment command"


class ToolError(ValueError):
    """A safe diagnostic that contains no wire text or secret values."""


class GiveUpError(ToolError):
    """The consecutive failure window exceeded the configured limit."""


class RetryError(OSError):
    """A retryable reply; retain the current lease and exact pending post."""


class RejectedError(ToolError):
    """An unsigned, empty 401; only enrolment and epoch renewal may handle it."""


class StopRequested(Exception):
    """The owner stopped this generation before its next phone exchange."""


def loopback(host):
    """Accept literals only, mapping localhost without a DNS lookup."""
    if host == "localhost":
        return "127.0.0.1"
    try:
        if ipaddress.ip_address(host).is_loopback:
            return host
    except ValueError:
        pass
    raise ToolError("host must be loopback; forward the port first")


def endpoint(value, phone=False):
    """Validate an endpoint before any socket, DNS request or key creation."""
    try:
        url = urlsplit("//" + value if phone else value)
        if (
            url.username is not None
            or url.password is not None
            or url.fragment
            or (phone and (url.path or url.query or url.port is None))
            or (not phone and (url.scheme not in ("http", "https") or not url.path.startswith("/")))
        ):
            raise ValueError
        host = loopback(url.hostname)
        port = url.port if url.port is not None else (443 if url.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError
        return host, port, url
    except (ValueError, TypeError) as err:
        raise ToolError("endpoint must name a loopback host and a valid port") from err


def key_file(path):
    """Create privately or read a regular, private file without following links."""
    flags = getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    getuid, fchmod = getattr(os, "getuid", None), getattr(os, "fchmod", None)
    # Windows keeps regular-file and size checks; inherited access rules are not checked.
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | flags, 0o600)
    except FileExistsError:
        fd = os.open(path, os.O_RDONLY | flags)
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or (
                getuid is not None and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != getuid())
            ):
                raise ToolError("key file must be a regular file owned by you with mode 0600") from None
            key = handle.read(33)
    else:
        with os.fdopen(fd, "wb") as handle:
            key = os.urandom(proto.KEY_BYTES)
            if fchmod is not None:
                fchmod(handle.fileno(), 0o600)
            handle.write(key)
            handle.flush()
            os.fsync(handle.fileno())
    if len(key) != proto.KEY_BYTES:
        raise ToolError("key file must contain exactly 32 bytes")
    return key


def server_auth_headers():
    """Bearer header for the local model server, from the environment only.

    The plug-and-play launcher keeps a random per-run key in memory and in this
    variable; it is never put on a command line, in a file or in a log.
    """
    key = os.environ.get("OPOS_GPU_LINK_SERVER_KEY", "")
    if key and all(32 < ord(c) < 127 for c in key):
        return {"Authorization": "Bearer " + key}
    return {}


def clean(text):
    """Drop controls except LF/TAB and drop lone surrogate code points."""
    return "".join(
        c for c in text if (unicodedata.category(c) != "Cc" or c in "\n\t") and not 0xD800 <= ord(c) <= 0xDFFF
    )


def cut(data, limit):
    """Keep a UTF-8 prefix ending at a whole character."""
    return data[:limit].decode("utf-8", errors="ignore").encode("utf-8")


def checked_reply(target, status, raw):
    """Validate the complete reply body before a caller changes state."""
    try:
        if status == 204 and (target.startswith("/v1/work?") or
                              re.fullmatch(r"/v1/lanes/g[1-3]/work\?wait=(0|[1-9]|1[0-9]|20)", target)):
            if raw:
                raise ValueError
            return {}
        value = proto.loads(raw, proto.WORK_REPLY_LIMIT)
        if status == 200 and target == "/v1/hello":
            keys = {"proto", "label", "epoch"}
            if (
                type(value.get("proto")) is not int
                or value["proto"] not in (1, proto.PROTO)
                or not proto.valid_label(value.get("label"))
                or proto.unhex(value.get("epoch"), proto.EPOCH_BYTES) is None
            ):
                raise ValueError
        elif status == 200 and (target == "/v1/status" or
                                re.fullmatch(r"/v1/lanes/g[1-3]/status", target)):
            keys = {"cancel"}
            if "proto" in value:
                if type(value["proto"]) is not int or value["proto"] != proto.PROTO:
                    raise ValueError
                keys.add("proto")
            cancel = value.get("cancel")
            if cancel is not None and proto.unhex(cancel, proto.LEASE_BYTES) is None:
                raise ValueError
        elif status == 200 and (target.startswith("/v1/work?") or
                                re.fullmatch(r"/v1/lanes/g[1-3]/work\?wait=(0|[1-9]|1[0-9]|20)", target)):
            lease = proto.unhex(value.get("lease"), proto.LEASE_BYTES)
            if target.startswith("/v1/work?"):
                keys = {"lease", "model_sha256", "question", "partial"}
                proto.work_reply(lease, value.get("model_sha256"), value.get("question"), value.get("partial"))
            else:
                keys = {"lease", "model_id", "question", "partial"}
                proto.extra_work_reply(lease, value.get("model_id"), value.get("question"), value.get("partial"))
            if any(clean(value[field]) != value[field] for field in ("question", "partial")):
                raise ValueError
        elif status == 200 and target == "/v1/advertise":
            keys = {"accepted"}
            if type(value.get("accepted")) is not int or not 0 <= value["accepted"] <= 3:
                raise ValueError
        elif target.endswith("/text") and (status == 200 or status in (409, 413) and "stored" in value):
            field = "acked" if status == 200 else "stored"
            keys = {field}
            count = value.get(field)
            if type(count) is not int or not 0 <= count <= proto.MAX_ANSWER_BYTES:
                raise ValueError
        else:
            keys = {"error"}
            proto.error_reply(value.get("error"))
        if set(value) != keys:
            raise ValueError
        return value
    except (ValueError, TypeError, KeyError):
        raise RetryError("Invalid phone reply; waiting to retry") from None


class DeadlineReader(io.RawIOBase):
    """Apply one monotonic deadline to every socket read."""

    def __init__(self, sock, deadline):
        self.sock, self.deadline = sock, deadline
        self.stream = sock.makefile("rb", buffering=0)

    def readable(self):
        return True

    def readinto(self, buffer):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError
        self.sock.settimeout(remaining)
        count = self.stream.readinto(buffer)
        if time.monotonic() >= self.deadline:
            raise TimeoutError
        return count

    def close(self):
        self.stream.close()
        super().close()


class ReplyReader(io.BufferedReader):
    """Bound status and header lines before the HTTP parser retains them."""

    def __init__(self, sock, deadline):
        super().__init__(DeadlineReader(sock, deadline))
        self.headers_done, self.used, self.lines = False, 0, 0
        self.terminated = False

    def readline(self, size=-1):
        if self.headers_done:
            return super().readline(size)
        bound = 8001 - self.used
        line = super().readline(bound if size < 0 else min(size, bound))
        self.used += len(line)
        self.lines += 1
        # Include the status line and final blank line in these bounds.
        if self.used > 8000 or self.lines > 42 or (self.lines > 41 and line != b"\r\n"):
            raise ToolError("reply headers too large")
        self.terminated = line == b"\r\n"
        return line


class BoundedResponse(http.client.HTTPResponse):
    """Use the standard HTTP parser with bounded, deadline-aware input."""

    def __init__(self, sock, deadline, **kwargs):
        class ReaderSocket:
            def makefile(self, *args):
                return ReplyReader(sock, deadline)

        super().__init__(ReaderSocket(), **kwargs)

    def begin(self):
        super().begin()
        if not self.fp.terminated:
            raise RetryError("Phone incomplete reply; waiting to retry")
        self.fp.headers_done = True


class PC:
    """One bounded connection per request, with fresh nonces and reply checks."""

    # The phone's signing epoch changes whenever its backend restarts. known_epoch survives the
    # epoch being cleared after a transport error, so a restart is noticed even then.
    known_epoch = None
    on_new_epoch = None

    def __init__(self, phone, key, label="Stand-in PC", request_limit=1):
        self.host, self.port, _ = endpoint(phone, phone=True)
        if not proto.valid_label(label):
            raise ToolError("label must match the wire label rule (1 to 24 characters)")
        self.key, self.label, self.epoch = key, label, None
        self.request_limit = request_limit
        self.lead_label = None
        self.lead_label_source = None
        self.label_epoch = None

    def send(self, method, target, body=b"", signed=True):
        headers = {"Host": "localhost", "Accept-Encoding": "identity", "Connection": "close",
                   "X-Link-Proto": str(proto.PROTO)}
        if method == "POST":
            headers["Content-Type"] = "application/json"
        nonce = os.urandom(proto.NONCE_BYTES)
        if signed:
            headers.update(
                {
                    "X-Link-Pc": proto.pc_id(self.key),
                    "X-Link-Nonce": nonce.hex(),
                    "X-Link-Mac": proto.request_mac(self.key, self.epoch, method, target, "", nonce, body),
                }
            )
        deadline = time.monotonic() + self.request_limit
        connection = http.client.HTTPConnection(self.host, self.port, timeout=self.request_limit)
        connection.response_class = lambda sock, **kw: BoundedResponse(sock, deadline=deadline, **kw)
        try:
            connection.request(method, target, body=body, headers=headers)
            with connection.getresponse() as response:
                fields = response.getheaders()
                if len(fields) > 40 or sum(len(k) + len(v) for k, v in fields) > 8000:
                    raise ToolError("reply headers too large")
                if response.getheader("Content-Encoding") not in (None, "identity"):
                    raise ToolError("compressed reply refused")
                if response.status == 204 and response.getheader("Content-Length", "0") != "0":
                    raise RetryError("Invalid phone reply; waiting to retry")
                raw = response.read(proto.WORK_REPLY_LIMIT + 1)
                if time.monotonic() >= deadline:
                    raise TimeoutError
                if len(raw) > proto.WORK_REPLY_LIMIT:
                    raise ToolError("reply body too large")
                if response.length:
                    raise OSError("incomplete reply")
                if signed:
                    macs = [v for k, v in fields if k.lower() == "x-link-mac"]
                    if response.status == 401 and not raw and not macs:
                        raise RejectedError("signed request refused")
                    expected = proto.reply_mac(
                        self.key, nonce, response.status, response.getheader("Content-Range", ""), raw
                    )
                    if len(macs) != 1 or not proto.same_mac(macs[0], expected):
                        raise ToolError("reply signature missing or wrong; stopped")
                return response.status, checked_reply(target, response.status, raw)
        finally:
            connection.close()

    def hello(self):
        """Read the unsigned protocol greeting and current signing epoch."""
        self.label_epoch = None  # Reconfirm with a signed reply, even for the same epoch.
        status, value = self.send("GET", "/v1/hello", signed=False)
        if status == 429 or status >= 500:
            raise RetryError("Phone hello unavailable; waiting to retry")
        if status != 200:
            raise ToolError("hello refused")
        epoch = proto.unhex(value.get("epoch"), proto.EPOCH_BYTES)
        if (
            set(value) != {"proto", "label", "epoch"}
            or type(value.get("proto")) is not int
            or value.get("proto") not in (1, proto.PROTO)
            or epoch is None
            or not proto.valid_label(value.get("label"))
        ):
            raise RetryError("Invalid phone reply; waiting to retry")
        previous = self.known_epoch
        self.epoch = self.known_epoch = epoch
        if previous is not None and previous != epoch and self.on_new_epoch is not None:
            try:
                self.on_new_epoch(epoch)
            except BaseException:
                self.known_epoch = previous  # the restart was not handled: report it again next time
                raise

    def status(self, lease=None, tokens=None, tps=None, error=None, state=None):
        """Publish liveness and optional speed without claiming GPU hardware."""
        payload = dict(
            state=state or ("error" if error else "busy" if lease else "ready"),
            lease=lease,
            copied=None,
            total=None,
            gpu=None,
            tokens=tokens,
            tps=tps,
            error=error,
        )
        confirmed = self.epoch is not None and self.label_epoch == self.epoch
        if confirmed:
            label = self.lead_label_source() if self.lead_label_source is not None else self.lead_label
            if label is not None and not proto.valid_model_label(label):
                raise ToolError("invalid lead model label")
            payload["lead_label"] = label
        # send() authenticates the reply before capability state can change.
        status, value = self.send("POST", "/v1/status", proto.dumps(payload))
        if status == 200:
            if value.get("proto") == proto.PROTO:
                self.label_epoch = self.epoch
            elif confirmed:
                self.label_epoch = None
                raise ToolError("phone protocol confirmation disappeared; stopped")
        return status, value

    def enrol_request(self):
        """Build one complete request for the owner's developer command stdin."""
        body = proto.dumps({"pc_label": self.label, "key": self.key.hex()})
        return (
            b"POST /v1/enrol HTTP/1.1\r\nHost: localhost\r\nContent-Type: application/json\r\n"
            + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode("ascii")
            + body
        )


class LanePC(PC):
    """Independent signed connection state for one additional computer answer lane."""

    def __init__(self, phone, key, label, pane, request_limit=1):
        if pane not in ("g1", "g2", "g3"):
            raise ToolError("invalid computer pane")
        super().__init__(phone, key, label, request_limit)
        self.pane = pane

    def send(self, method, target, body=b"", signed=True):
        if method == "GET" and target.startswith("/v1/work?"):
            target = f"/v1/lanes/{self.pane}/work?" + target.split("?", 1)[1]
        return super().send(method, target, body, signed)

    def status(self, lease=None, tokens=None, tps=None, error=None, state=None):
        payload = {
            "state": state or ("error" if error else "busy" if lease else "ready"),
            "lease": lease, "copied": None, "total": None, "gpu": None,
            "tokens": tokens, "tps": tps, "error": error,
        }
        return self.send("POST", f"/v1/lanes/{self.pane}/status", proto.dumps(payload))


class PracticeSource:
    """Fixed, explicitly simulated text with a resumable prefix."""

    def __init__(self, job):
        partial = job["partial"].encode()
        practice = clean(PRACTICE).encode()
        self.data = practice if practice.startswith(partial) else partial + practice
        self.finish = "length" if len(self.data) > proto.MAX_ANSWER_BYTES else "stop"
        self.data = cut(self.data, proto.MAX_ANSWER_BYTES)

    def snapshot(self):
        """Return buffered text, completion, finish reason, token estimate and error."""
        return self.data, True, self.finish, None, False

    def close(self):
        """There is no worker or socket in practice mode."""


def _stall_seconds():
    """Seconds with no new stream bytes, after the first byte, before the server counts as stalled."""
    try:
        value = float(os.environ.get("OPOS_GPU_LINK_STALL_SECONDS", "12"))
    except ValueError:
        return 12.0
    return value if 1.0 <= value <= 30.0 else 12.0


class ServerSource:
    """Read bounded SSE in a worker so phone status continues during server waits."""

    # Before the first byte the server may still be reading a long resume prefix, so it gets the
    # full 30 s. Once text is flowing, a quiet stream is a stall: STALL_SECONDS ends the read and
    # the answer pauses and resumes like a crash (error code "server"), instead of waiting 30 s.
    FIRST_BYTE_SECONDS = 30

    def __init__(self, job, url, model, retry_budget=None):
        self.host, self.port, self.url = endpoint(url)
        self.model, self.job = model, job
        self.lock, self.stop = threading.Lock(), threading.Event()
        self.data = job["partial"].encode()
        self.partial_bytes = len(self.data)
        self.done, self.finish, self.tokens, self.error = False, "stop", None, False
        self.error_code = "server"
        self.guard_enabled = GuardState is not None and os.environ.get("OPOS_GPU_LINK_GUARD", "1") != "0"
        self.retry_budget = retry_budget if retry_budget is not None else GuardRetryBudget()
        self.seed, self.safer_sampling = self.retry_budget.begin(job)
        self.guard_reason = self.attempt_reason = None
        self.guard = None
        self.sock = None
        self.worker = threading.Thread(target=self._run, name="standin-stream", daemon=True)
        self.worker.start()

    def snapshot(self):
        """Take a consistent copy of the reader state."""
        with self.lock:
            return (
                self.data,
                self.done,
                self.finish,
                self.tokens if self.tokens is not None else len(self.data[self.partial_bytes :].decode().split()),
                self.error,
            )

    def _event(self, value):
        if "model" in value and value["model"] != self.model:
            raise ToolError("wrong model in server stream")
        choices = value.get("choices", [])
        if choices:
            choice = choices[0]
            piece = choice.get("delta", {}).get("content") or ""
            if not isinstance(piece, str):
                raise ToolError("invalid server stream")
            with self.lock:
                if self.guard is not None:
                    self.attempt_reason = self.guard.feed(piece)
                    self.generated_bytes += len(clean(piece).encode())
                    self.data = cut(clean(self.guard.safe_text).encode(), proto.MAX_ANSWER_BYTES)
                    if self.attempt_reason is None and self.generated_bytes > proto.MAX_ANSWER_BYTES:
                        self.attempt_reason = "runaway_length"
                    if self.attempt_reason:
                        self.guard_reason = self.attempt_reason
                        return True
                    if choice.get("finish_reason"):
                        self.finish = "length" if choice["finish_reason"] == "length" else "stop"
                else:
                    cleaned = clean(piece).encode()
                    room = proto.MAX_ANSWER_BYTES - len(self.data)
                    self.data += cut(cleaned, room)
                    if len(cleaned) >= room:
                        self.finish = "length"
                        return True
                    if choice.get("finish_reason"):
                        self.finish = "length" if choice["finish_reason"] == "length" else "stop"
        usage = value.get("usage") or {}
        tokens = usage.get("completion_tokens")
        if type(tokens) is int and 0 <= tokens <= proto.MAX_WHOLE:
            with self.lock:
                self.tokens = tokens
        return False

    def _read(self, response):
        total, ended = 0, False
        while not self.stop.is_set():
            line = response.readline(65537)
            if self.stop.is_set():
                return  # closed while blocked: ignore late bytes
            if line and total == 0:
                with self.lock:
                    if self.sock is not None:
                        self.sock.settimeout(_stall_seconds())
            total += len(line)
            if len(line) > 65536 or total > 2 * 1024 * 1024:
                raise ToolError("server stream too large")
            if not line:
                if not ended:
                    raise ToolError("server stream ended early")
                return
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                return
            value = json.loads(data)
            if self._event(value):
                return
            ended = ended or any(c.get("finish_reason") for c in value.get("choices", []))

    def _stream_once(self, prefix):
        """Own exactly one request; a guard return closes it before any retry."""
        connection_type = http.client.HTTPSConnection if self.url.scheme == "https" else http.client.HTTPConnection
        connection = connection_type(self.host, self.port, timeout=2)
        try:
            messages = default_system_message([{"role": "user", "content": self.job["question"]}])
            if prefix:
                messages.append({"role": "assistant", "content": prefix})
            body = {"model": self.model, "messages": messages, "stream": True, "stream_options": {"include_usage": True}}
            sampling = self.job.get("sampling", {})
            for name in ("temperature", "top_p", "repeat_penalty"):
                if name in sampling:
                    body[name] = sampling[name]
            if self.guard_enabled:
                body["seed"] = self.seed
                if self.safer_sampling:
                    body.update(temperature=min(sampling.get("temperature", 1.0), GUARD_RETRY_TEMPERATURE),
                                top_p=GUARD_RETRY_TOP_P,
                                repeat_penalty=max(sampling.get("repeat_penalty", 1.0), GUARD_RETRY_REPEAT_PENALTY))
            effort = os.environ.get("OPOS_GPU_LINK_REASONING_EFFORT", "none").strip()
            if effort and effort != "default":
                body["reasoning_effort"] = effort  # "none": skip hidden thinking so text starts in about a second
            payload = json.dumps(body, ensure_ascii=False).encode()
            connection.connect()
            with self.lock:
                self.sock = connection.sock
                self.sock.settimeout(self.FIRST_BYTE_SECONDS)
            if self.stop.is_set():
                return
            target = self.url.path + ("?" + self.url.query if self.url.query else "")
            connection.request(
                "POST", target, payload,
                {"Content-Type": "application/json", "Accept-Encoding": "identity", **server_auth_headers()}
            )
            with connection.getresponse() as response:
                if response.status != 200 or response.getheader("Content-Encoding") not in (None, "identity"):
                    raise ToolError("chat-completions server refused stream")
                if response.getheader("Content-Type", "").split(";")[0] != "text/event-stream":
                    raise ToolError("chat-completions server must stream events")
                self._read(response)
        finally:
            connection.close()
            with self.lock:
                self.sock = None

    @staticmethod
    def _new_salad():
        """A fresh background word-salad judge, or None when unconfigured/disabled."""
        if gpu_link_salad is None:
            return None
        judge = gpu_link_salad.default_judge()
        return gpu_link_salad.BackgroundSalad(judge) if judge is not None else None

    def _run(self):
        try:
            while not self.stop.is_set():
                with self.lock:
                    prefix = self.data.decode()
                    self.guard = GuardState(initial_text=prefix, salad=self._new_salad()) if self.guard_enabled else None
                    self.generated_bytes = len(self.data)
                    self.attempt_reason = None
                    self.tokens, self.finish = None, "stop"
                self._stream_once(prefix)
                if self.stop.is_set():
                    return
                with self.lock:
                    if self.guard is not None and self.attempt_reason is None:
                        self.attempt_reason = self.guard.feed("", final=True)
                        self.data = cut(clean(self.guard.safe_text).encode(), proto.MAX_ANSWER_BYTES)
                    reason = self.attempt_reason
                    if reason:
                        self.guard_reason = reason
                if reason is None:
                    return
                seed = self.retry_budget.retry()
                if seed is None:
                    with self.lock:
                        self.error, self.error_code = True, "garbled"
                    return
                self.seed, self.safer_sampling = seed, True
        except (OSError, ValueError, http.client.HTTPException, KeyError, TypeError, AttributeError):
            with self.lock:
                self.error = not self.stop.is_set()
        finally:
            with self.lock:
                self.done = True

    def close(self):
        """Interrupt the read and join the worker before returning."""
        self.stop.set()
        with self.lock:
            sock = self.sock
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # The reader may already have closed its connection.
        self.worker.join(4)
        if self.worker.is_alive():
            if os.name == "nt":
                # Windows cannot wake a thread blocked in recv from another thread (neither shutdown nor close does).
                # The shutdown above already sent FIN, so the server drops the stream; the daemon thread ends when the
                # peer closes or the 30 s read timeout fires, and its late bytes are ignored because stop is set.
                return
            raise ToolError("server stream did not stop")


# A model server that stalls or crashes mid-answer is a recoverable fault: the phone keeps the
# acknowledged text and the answer resumes from it once the server answers again.
RECOVERABLE_ERRORS = frozenset({"server"})
RECOVERY_MIN_HOLD = 3.0       # long enough for the phone to see two lease-less statuses and pause
RECOVERY_MAX_HOLD = 180.0     # then ask for the work again even if no readiness probe said so
RECOVERY_TRIES = 3            # recoveries in a row with no new acknowledged text before failing


class StandIn:
    """A single-step reactor; pausing calls to step simulates a pulled cable."""

    def __init__(
        self, pc, source=PracticeSource, rate=4, emit=print, show_text=False, clock=time.monotonic, give_up_after=300,
        server_ready=None,
    ):
        if not math.isfinite(rate) or not 0 < rate <= 4:
            raise ToolError("rate must be greater than zero and at most 4")
        self.pc, self.source_factory, self.rate = pc, source, rate
        self.emit, self.show_text, self.clock = emit, show_text, clock
        self.job, self.source = None, None
        self.offset, self.next_post, self.next_status, self.next_poll = 0, 0, 0, 0
        if not math.isfinite(give_up_after) or give_up_after < 0:
            raise ToolError("give-up-after must be finite and nonnegative")
        self.give_up_after = give_up_after
        self.failed_since, self.last_failure_line = None, None
        self.post_failed_since = None
        self.retry_at, self.pending = 0, None
        self.started = clock()
        self.stop_event = None
        self.server_ready = server_ready
        self.holding_since, self.next_ready_check = None, 0
        self.recovery = None  # (question, tries, acknowledged bytes) of the answer last held

    def _check_stop(self):
        if self.stop_event is not None and self.stop_event.is_set():
            raise StopRequested

    def close(self):
        """Drop generation; the phone keeps its acknowledged partial text."""
        if self.source is not None:
            self.source.close()
        self.source, self.job, self.pending = None, None, None
        self.post_failed_since = None

    def _request(self, send):
        """Repeat the same operation once after an epoch change, with a fresh nonce."""
        try:
            self._check_stop()
            return send()
        except RejectedError:
            previous = self.pc.epoch
            self._check_stop()
            self.pc.hello()
            if previous == self.pc.epoch:
                raise ToolError("saved key not accepted; use owner recovery on the phone") from None
            try:
                self._check_stop()
                return send()
            except RejectedError:
                raise RetryError("Phone epoch renewed; waiting to retry") from None

    def _exchange(self, method, target, body=b""):
        return self._accepted(self._request(lambda: self.pc.send(method, target, body)))

    def _accepted(self, reply):
        status, value = reply
        if status >= 500:
            raise RetryError("Phone server error; waiting to retry")
        if status == 429 or status == 400 and value.get("error") == "state":
            raise RetryError("Phone service unavailable; waiting to retry")
        self.failed_since = None
        if self.post_failed_since is None:
            self.last_failure_line = None
        return status, value

    def _send_status(self, lease=None, tokens=None, tps=None, error=None, state=None):
        self._check_stop()
        return self._accepted(self._request(lambda: self.pc.status(lease, tokens, tps, error, state)))

    def _failure(self, line):
        now = self.clock()
        if self.failed_since is None:
            self.failed_since = now
        start = min(value for value in (self.failed_since, self.post_failed_since) if value is not None)
        if self.give_up_after and now - start >= self.give_up_after:
            raise GiveUpError("Phone exchanges failed too long; stopped")
        if self.last_failure_line is None or now - self.last_failure_line >= 30:
            self.emit(line)
            self.last_failure_line = now
        self.retry_at = now + 1

    def _status(self):
        tokens, tps = None, None
        if self.source:
            data, _, _, tokens, error = self.source.snapshot()
            code = getattr(self.source, "error_code", "server")
            draining = error and code == "garbled" and (self.offset < len(data) or self.pending is not None)
            if error and not draining and code in RECOVERABLE_ERRORS and self._hold_for_recovery():
                return
            if error and not draining:
                self._send_status(self.job["lease"], error=code)
                self.emit("Answer stopped: chat-completions server error")
                self.recovery = None  # the answer has ended; a new run gets a fresh budget
                self.close()
                return
            if tokens is not None:
                tps = min(100000, round(tokens / max(0.001, self.clock() - self.started), 3))
        warming = self.source is not None and getattr(self.source, "warming", False)
        state = "loading" if warming or self.job is None and self.holding_since is not None else None
        status, value = self._send_status(self.job["lease"] if self.job else None, tokens, tps, state=state)
        if status == 404 and self.job and value.get("error") == "lease":
            self.recovery = None
            self.close()
            self.emit("Lease ended; polling again")
            self._status()
            return
        if status != 200:
            raise ToolError("status refused")
        self.next_status = self.clock() + 1
        if self.job and value.get("cancel") == self.job["lease"]:
            self.recovery = None
            self.close()
            self.emit("Answer cancelled by phone")
        else:
            self.emit("Status warming" if state == "loading" else "Status busy" if self.job else "Status ready")

    def _hold_for_recovery(self):
        """Give the lease back without an error so the phone pauses the answer and keeps its text."""
        question, offset = self.job["question"], self.offset
        tries = 1
        if self.recovery is not None and self.recovery[0] == question and offset == self.recovery[2]:
            tries = self.recovery[1] + 1
        if tries > RECOVERY_TRIES:
            self.recovery = None
            return False
        self.recovery = (question, tries, offset)
        self.close()
        self.holding_since, self.next_ready_check = self.clock(), 0
        self.next_status = 0
        self.emit("Answer held: model server recovering")
        return True

    def _recovered(self):
        """True once a held answer may be asked for again."""
        if self.holding_since is None:
            return True
        now = self.clock()
        held = now - self.holding_since
        if held < RECOVERY_MIN_HOLD or now < self.next_ready_check:
            return False
        ready = held >= RECOVERY_MAX_HOLD
        if not ready:
            try:
                ready = self.server_ready is None or bool(self.server_ready())
            except Exception:
                ready = False
            finally:
                # Counted from the end of the probe: a hung server makes the probe itself slow.
                self.next_ready_check = self.clock() + 1
        if ready:
            self.holding_since = None
            self.emit("Model server answering again; resuming")
        return ready

    def _work(self):
        self._check_stop()
        status, job = self._exchange("GET", "/v1/work?wait=0")
        self._check_stop()
        self.next_poll = self.clock() + 0.25
        if status == 204:
            return
        if status != 200:
            raise ToolError("work poll refused")
        self.job, self.offset = job, len(job["partial"].encode())
        if self.recovery is not None and (self.recovery[0] != job["question"] or self.offset < self.recovery[2]):
            self.recovery = None  # a different or restarted answer starts with a fresh budget
        self.source = self.source_factory(job)
        self.started, self.next_status = self.clock(), 0
        self.emit(f"Work received; partial {self.offset} bytes")
        if self.show_text:
            self.emit("Question: " + json.dumps(clean(job["question"]), ensure_ascii=False))

    def _post_reply(self, raw, piece, data):
        """Keep the pending post and its failure window until its reply is accepted."""
        try:
            self._check_stop()
            status, value = self._exchange("POST", f"/v1/runs/{self.job['lease']}/text", raw)
            if status in (409, 413) and "stored" in value:
                stored = value["stored"]
                if stored > len(data) or cut(data, stored) != data[:stored]:
                    raise RetryError("Invalid stored byte offset; waiting to retry")
            if status == 200 and value["acked"] != self.offset + len(piece):
                raise RetryError("Invalid text acknowledgement; waiting to retry")
            return status, value
        except (OSError, http.client.HTTPException):
            if self.post_failed_since is None:
                self.post_failed_since = self.clock()
            raise

    def _post(self):
        self._check_stop()
        data, done, finish, _, error = self.source.snapshot()
        self._check_stop()
        garbled = error and getattr(self.source, "error_code", "server") == "garbled"
        if error and self.pending is None and (not garbled or self.offset >= len(data)):
            self.next_status = 0
            return
        if self.offset > len(data):
            raise ToolError("stored offset exceeds buffered answer")
        if self.pending is None:
            piece = cut(data[self.offset :], 256)
            final = done and not error and self.offset + len(piece) == len(data)
            if not piece and not final:
                return
            if final:
                self._status()  # Store the last speed before the final post.
                if self.job is None:
                    return
            raw = proto.dumps(
                dict(offset=self.offset, text=piece.decode(), done=final, finish=finish if final else None)
            )
            self.pending = raw, piece, final
        raw, piece, final = self.pending
        status, value = self._post_reply(raw, piece, data)
        self.pending = None
        if status == 200:
            self.post_failed_since = None
            self.last_failure_line = None
        self.next_post = self.clock() + 1 / self.rate
        if status in (409, 413) and "stored" in value:
            self.offset = value["stored"]
            self.emit(f"Offset recovered; stored {self.offset} bytes")
        elif status == 404:
            self.close()
            self.emit("Lease ended; polling again")
        elif status == 200:
            self.offset += len(piece)
            self.emit(f"Text acknowledged; {self.offset} bytes" + ("; final" if final else ""))
            if self.show_text:
                self.emit("Text: " + json.dumps(piece.decode(), ensure_ascii=False))
            if final:
                self.recovery = None
                self.close()
        else:
            raise ToolError("text post refused")

    def step(self):
        """Perform bounded work; callers close this object even after a failure."""
        self._check_stop()
        if self.clock() < self.retry_at:
            return
        try:
            if self.pc.epoch is None:
                self.pc.hello()
                if self.failed_since is None:
                    self.emit("Hello accepted")
            if self.clock() >= self.next_status:
                self._status()
            if self.job is None and self.clock() >= self.next_poll and self._recovered():
                self._check_stop()
                self._work()
            if self.job is not None and self.clock() >= self.next_post:
                self._check_stop()
                self._post()
        except RetryError as err:
            self._failure(str(err))
        except (OSError, http.client.HTTPException):
            self.close()
            self.pc.epoch = None
            self.next_status = 0
            self._failure("Phone unreachable; waiting to retry")

    def run(self, stop):
        """Retry bounded failures until stopped or the consecutive window expires."""
        self.stop_event = stop
        try:
            while not stop.is_set():
                self.step()
                stop.wait(max(0.05, self.retry_at - self.clock()))
        except StopRequested:
            pass
        finally:
            self.close()


def arguments(argv=None):
    """Parse and validate all connection options before touching key storage."""
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phone", default="127.0.0.1:8767", help="forwarded loopback HOST:PORT (default: %(default)s)")
    parser.add_argument(
        "--label", default="Stand-in PC", help="wire label: letters, digits, spaces and hyphens; 1 to 24 chars"
    )
    parser.add_argument("--key-file", required=True, help="raw 32-byte key file; created with mode 0600 if missing")
    parser.add_argument(
        "--enrol-request", action="store_true", help="write enrolment HTTP request to a pipe or socket; never connect"
    )
    parser.add_argument(
        "--text", choices=("practice", "server"), default="practice", help="text source (default: practice)"
    )
    parser.add_argument("--server", help="full loopback chat-completions endpoint URL; existing server only")
    parser.add_argument("--model", help="model name for the existing chat-completions server")
    parser.add_argument(
        "--rate", type=float, default=4, help="text posts per second, greater than 0 and at most 4 (default: 4)"
    )
    parser.add_argument(
        "--give-up-after", type=float, default=300, help="consecutive failure limit in seconds (default: 300; 0: never)"
    )
    parser.add_argument("--show-text", action="store_true", help="include questions and answer text in event lines")
    args = parser.parse_args(argv)
    endpoint(args.phone, phone=True)
    if args.server:
        endpoint(args.server)
    if not proto.valid_label(args.label):
        raise ToolError("invalid label; use 1 to 24 letters, digits, spaces or hyphens with alphanumeric ends")
    if not math.isfinite(args.rate) or not 0 < args.rate <= 4:
        raise ToolError("rate must be greater than zero and at most 4")
    if not math.isfinite(args.give_up_after) or args.give_up_after < 0:
        raise ToolError("give-up-after must be finite and nonnegative")
    if args.text == "server" and (not args.server or not args.model):
        raise ToolError("server text needs --server and --model")
    return args


def enrol_stdout():
    """Require a pipe or socket where descriptor type checks are available."""
    output = sys.stdout
    if output is None or output.closed or output.isatty():
        return False
    try:
        mode = os.fstat(output.fileno()).st_mode
    except OSError as err:
        return err.errno != errno.EBADF
    except (AttributeError, ValueError):
        return True  # Some platforms cannot identify the non-terminal descriptor type.
    return stat.S_ISFIFO(mode) or stat.S_ISSOCK(mode)


def main(argv=None):
    """Run until interrupted and print only safe event diagnostics."""
    try:
        args = arguments(argv)
        if args.enrol_request and not enrol_stdout():
            print(ENROL_REFUSED, file=sys.stderr)
            return 2
        pc = PC(args.phone, key_file(args.key_file), args.label)

        def emit(line):
            print(line, flush=True)

        if args.enrol_request:
            code = proto.code(pc.label, pc.key)
            print(f"Compare code on phone: {code[:3]} {code[3:]}", file=sys.stderr, flush=True)
            try:
                sys.stdout.buffer.write(pc.enrol_request())
                sys.stdout.buffer.flush()
            except (OSError, ValueError):
                # Avoid a second failing flush changing the interpreter's exit status to 120.
                fd = os.open(os.devnull, os.O_WRONLY)
                try:
                    os.dup2(fd, 1)
                finally:
                    os.close(fd)
                print(ENROL_REFUSED, file=sys.stderr)
                return 2
            return 0
        budget = GuardRetryBudget()
        source = (PracticeSource if args.text == "practice" else
                  lambda job: ServerSource(job, args.server, args.model, budget))
        StandIn(pc, source, args.rate, emit, args.show_text, give_up_after=args.give_up_after).run(threading.Event())
        return 0
    except GiveUpError as err:
        print(str(err), file=sys.stderr)
        return 3
    except KeyboardInterrupt:
        print("Stand-in stopped")
        return 0
    except (ToolError, proto.ProtoError) as err:
        print("Stand-in stopped: " + str(err), file=sys.stderr)
        return 1
    except (OSError, http.client.HTTPException):
        print("Stand-in stopped: local file or connection error", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit("Start opos_gpu_link.py so the computer's permission and protected key storage are enforced.")

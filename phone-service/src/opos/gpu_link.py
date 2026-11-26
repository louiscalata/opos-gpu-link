# SPDX-License-Identifier: Apache-2.0
"""Owner-mode GPU Link state, without sockets.

The last 64 finished and page-cancelled leases live until forget or restart,
oldest evicted first. Final retries match the remembered final post. Paused leases
are not reusable. A condition releases the state lock during long polls;
each lane's accepted poll advances its generation and wakes its previous poll with 204.

One background thread hashes a regular model file in bounded chunks, without the
state lock. A cache binds the hash to path, size, nanosecond mtime and file identity.
Checking/error models yield no work and model requests get signed 404 errors.
Call close() to wake polls and join the hashing thread before releasing the store.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import stat
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, BinaryIO

from opos import ai_answers as answers_api
from opos import gpu_link_proto as proto
from opos.store import DurabilityError, Store


def display_label(label: object) -> object:
    """Screen name for a paired PC; the saved pairing label itself never changes.

    OPOS_GPU_LINK_PC_DISPLAY maps saved labels to what the phone shows, for example
    "M5 Pro PC=M5 Pro MacBook Pro" (pairs separated by ";"). Renaming the saved label
    would force owner recovery, so only the screen text is mapped.
    """
    if not isinstance(label, str):
        return label
    for item in os.environ.get("OPOS_GPU_LINK_PC_DISPLAY", "").split(";"):
        saved, sep, shown = item.partition("=")
        if sep and saved.strip() == label and proto.valid_label(shown.strip()):
            return shown.strip()
    return label

HISTORY_LIMIT = 64
LINK_SECONDS = 2.5
HASH_RETRY_SECONDS = 5.0


@dataclass(frozen=True)
class Reply:
    """Immutable response; file is (path, byte start, byte length), if present."""

    status: int
    headers: tuple = ()
    body: bytes = b""
    file: tuple | None = None
    sent: Callable[[], None] | None = None
    failed: Callable[[], None] | None = None
    file_identity: dict | None = None
    file_error: Reply | None = None


class ModelChangedError(OSError):
    """The advertised model changed; stop sending this response."""


def _error(status: int, code: str) -> Reply:
    return Reply(status, (), proto.error_reply(code))


def _identity(path: Path) -> dict:
    return _file_identity(path, path.stat())


def _file_identity(path: Path, info: os.stat_result) -> dict:
    if not stat.S_ISREG(info.st_mode):
        raise OSError("model")
    return {
        "path": str(path),
        "size": info.st_size,
        "mtime_ns": info.st_mtime_ns,
        "device": info.st_dev,
        "inode": info.st_ino,
    }


class LinkService:
    """Serialize link state before entering the answer store's own lock.

    Authenticated failures still consume their nonce. Storage failures restore
    lease and rate state; speed metadata writes are best effort.
    Page mutations may raise OSError so their caller can report failed storage.
    The listener reports complete writes through each work reply's callbacks.
    """

    def __init__(
        self,
        answers: answers_api.AnswerStore,
        store: Store | None = None,
        model_path: str | Path | None = None,
        label: str = "OPOS phone",
        clock: Callable[[], float] = time.monotonic,
        rand: Callable[[int], bytes] = os.urandom,
    ) -> None:
        if not proto.valid_label(label):
            raise ValueError("label")
        self._lock = threading.RLock()
        self._changed = threading.Condition(self._lock)
        self._answers = answers
        self._store = store if store is not None else Store()
        self._clock, self._rand, self._label = clock, rand, label
        self._epoch = rand(16)
        self._nonces: set[bytes] = set()
        self._buckets: dict[str, tuple[float, float]] = {}
        self._pending: tuple[str, bytes, float] | None = None
        self._denials = 0
        self._pc: tuple[str, bytes] | None = None
        self._pairing_sweep_pending = True
        try:
            self._store.sweep_temps("gpu-link-pc.json")
        except OSError:
            pass
        else:
            self._pairing_sweep_pending = False
        saved, _ = self._store.read_json("gpu-link-pc.json", {})
        key = proto.unhex(saved.get("key"), 32)
        if key is not None and proto.valid_label(saved.get("label")):
            self._pc = (saved["label"], key)
        self._status: dict | None = None
        self._lead_label: str | None = None
        self._last_status: float | None = None
        self._lease: dict | None = None  # Legacy lead lane; keep its single-lane contract.
        self._extra_leases: dict[str, dict | None] = {pane: None for pane in ("g1", "g2", "g3")}
        self._advertised: dict[str, dict] = {}
        self._extra_status: dict[str, dict] = {}
        self._extra_last_status: dict[str, float] = {}
        self._extra_polls: dict[str, int] = {pane: 0 for pane in self._extra_leases}
        self._extra_speeds: dict[str, dict] = {}
        self._ending_extra: dict[str, str] = {}
        self._ending_answer: str | None = None
        self._storage_fault: str | None = None
        self._speed: dict | None = None
        self._history: OrderedDict[bytes, tuple[str, dict | None, int | None, bytes]] = OrderedDict()
        self._poll = 0
        self._closed = False
        self._model_path = Path(model_path).absolute() if model_path else None
        name = self._model_path.stem if self._model_path else ""
        self._model = {"state": "none", "name": self._display_name(name), "size": None}
        self._model_id: dict | None = None
        self._model_hash: str | None = None
        self._hasher: threading.Thread | None = None
        self._hash_failure: tuple[dict, float] | None = None
        self._hash_stop = threading.Event()
        with self._lock:
            self._check_model()

    @staticmethod
    def _display_name(name: str) -> str:
        return "".join(c for c in name if " " <= c <= "~")[:64]

    def set_model_name(self, name: str) -> None:
        """Set the printable display name supplied by the listener's environment."""
        with self._lock:
            self._model["name"] = self._display_name(name)

    def close(self) -> None:
        """Pause running work, end waiting polls and join the background reader."""
        with self._lock:
            if not self._closed:
                self._closed = True
                self._hash_stop.set()
                try:
                    for pane in ("gpu", *self._extra_leases):
                        if pane != "gpu" and pane not in self._advertised and self._get_lease(pane) is None:
                            continue
                        if self._get_lease(pane) is not None:
                            self._pause(pane)
                        else:
                            answer = self._answers.current(pane)
                            if answer is not None and answer["state"] in ("loading", "answering"):
                                self._answers.pause(answer["id"])
                except (OSError, answers_api.AnswerError):
                    # A later service reconciles running work if storage is unavailable.
                    pass
            self._changed.notify_all()
            thread = self._hasher
        if thread is not None and thread.ident is not None:
            thread.join()

    def open_model(self, path: Path, target: str, identity: dict | None = None) -> BinaryIO:
        """Open only the still-hashed file before the listener sends any headers.

        The caller owns the returned stream. A changed file aborts the response;
        the peer must still hash the completed download, since an open regular
        file can be modified during transfer by its local owner.
        """
        with self._lock:
            if (
                self._closed
                or path != self._model_path
                or self._model["state"] != "ready"
                or target != f"/v1/models/{self._model_hash}"
            ):
                raise ModelChangedError("model changed")
            stream = path.open("rb")
            try:
                self.check_model_stream(stream, identity or self._model_id)
                return stream
            except OSError:
                stream.close()
                raise

    def check_model_stream(self, stream: BinaryIO, identity: dict) -> None:
        """Compare the open file with this reply's hashed identity, not a newer hash."""
        if _file_identity(self._model_path, os.fstat(stream.fileno())) != identity:
            with self._lock:
                self._model["state"] = "checking"
            raise ModelChangedError("model changed")

    @staticmethod
    def unsigned(method: str, target: str) -> bool:
        """Return whether this exact route accepts requests without a PC key."""
        return (method, target) in (("GET", "/v1/hello"), ("POST", "/v1/enrol"))

    @staticmethod
    def permits_range(method: str, target: str) -> bool:
        """Return whether this route accepts a model byte-range header."""
        try:
            return proto.parse_target(method, target)[0] == "model"
        except proto.ProtoError:
            return False

    def body_limit(self, method: str, target: str) -> int:
        """Return a raw body bound, zero for GET and unrecognised routes."""
        try:
            route = proto.parse_target(method, target)[0]
        except proto.ProtoError:
            return 0
        return {"enrol": 1024, "status": 2048, "lane_status": 2048,
                "advertise": 2048, "text": 8192}.get(route, 0)

    def _token(self, name: str, rate: int) -> bool:
        now = self._clock()
        left, last = self._buckets.get(name, (float(rate), now))
        left = min(float(rate), left + max(0, now - last) * rate)
        allowed = left >= 1
        self._buckets[name] = (left - int(allowed), now)
        return allowed

    def _authenticate(self, method: str, target: str, headers: Any, body: bytes) -> tuple | None:
        ident = proto.unhex(headers.get("X-Link-Pc"), 8)
        nonce = proto.unhex(headers.get("X-Link-Nonce"), 12)
        mac = headers.get("X-Link-Mac")
        if ident is None or nonce is None or proto.unhex(mac, 32) is None or self._pc is None:
            return None
        key = self._pc[1]
        if ident.hex() != proto.pc_id(key):
            return None
        try:
            expected = proto.request_mac(key, self._epoch, method, target, headers.get("Range", ""), nonce, body)
        except proto.ProtoError:
            return None
        if not proto.same_mac(mac, expected) or nonce in self._nonces:
            return None
        if len(self._nonces) >= proto.NONCES_PER_PC:
            self._epoch = self._rand(16)
            self._nonces.clear()
            return None
        self._nonces.add(nonce)
        return key, nonce

    @staticmethod
    def _signed(reply: Reply, auth: tuple) -> Reply:
        content_range = dict(reply.headers).get("Content-Range", "")
        mac = proto.reply_mac(*auth, reply.status, content_range, None if reply.file else reply.body)
        return replace(
            reply,
            headers=reply.headers + (("X-Link-Mac", mac),),
            file_error=LinkService._signed(reply.file_error, auth) if reply.file_error else None,
        )

    def handle(self, method: str, target: str, headers: Any, body: bytes) -> Reply:
        """Validate a bounded request, atomically authenticate it, and return a reply.

        Oversize input is refused before hashing, so it has not been authenticated.
        Framing failures on signed targets are empty unsigned 401 responses.
        """
        with self._changed:
            unsigned = self.unsigned(method, target)
            if not isinstance(body, bytes):
                return _error(400, "request") if unsigned else Reply(401)
            if len(body) > self.body_limit(method, target):
                return _error(413, "too_long") if unsigned else Reply(401)
            if headers.get("Range") is not None and not self.permits_range(method, target):
                return _error(400, "request") if unsigned else Reply(401)
            if not unsigned and (
                headers.get("Transfer-Encoding") is not None
                or (method == "POST" and headers.get("Content-Length") is None)
            ):
                return Reply(401)
            auth = None if unsigned else self._authenticate(method, target, headers, body)
            if not unsigned and auth is None:
                return Reply(401)
            buckets = self._buckets.copy()
            try:
                route = proto.parse_target(method, target)
                if self._closed:
                    reply = _error(400, "state")
                else:
                    reply = self._dispatch(route, headers, body)
            except proto.ProtoError as err:
                reply = _error(413 if err.code == "too_long" else 400, err.code)
            except OSError:
                if auth is not None:
                    try:
                        answer = self._answers.current("gpu") if route[0] in ("work", "text", "status") else None
                    except OSError:
                        answer = None
                    self._storage_fault = answer["id"] if answer is not None else ""
                # Work can release the lock while waiting. Never roll back tokens
                # consumed by another request during that wait.
                if method == "POST" and target.startswith("/v1/runs/"):
                    self._buckets = buckets
                reply = _error(500, "state")
            except answers_api.StateError:
                reply = _error(404, "lease")
            except Exception:
                reply = _error(400, "request")
            return self._signed(reply, auth) if auth is not None else reply

    def _dispatch(self, route: tuple, headers: Any, body: bytes) -> Reply:
        kind = route[0]
        # Old companions strictly validate both hello and status reply keys.
        # The header opts into v2 response shapes; the signed reply authenticates
        # the capability before a new companion sends its optional body field.
        version = proto.PROTO if headers.get("X-Link-Proto") == str(proto.PROTO) else proto.LEGACY_PROTO
        if kind == "hello":
            return (
                Reply(200, (), proto.hello_body(self._label, self._epoch, proto_version=version))
                if self._token("hello", 10)
                else _error(429, "rate")
            )
        if kind == "enrol":
            return self._enrol(body)
        if kind == "status":
            status = proto.parse_status(body)
            if "lead_label" in status and version < proto.PROTO:
                raise proto.ProtoError("request")
            return self._record_status(status, proto_version=version)
        if kind == "lane_status":
            status = proto.parse_status(body)
            if "lead_label" in status:
                raise proto.ProtoError("request")
            return self._record_status(status, route[1], proto_version=version)
        if kind == "advertise":
            return self._advertise(proto.parse_advertise(body))
        if kind == "work":
            return self._work(route[1])
        if kind == "lane_work":
            return self._work(route[2], route[1])
        if kind == "text":
            return self._text(route[1], body)
        return self._model_reply(route[1], headers.get("Range"))

    def _expire(self) -> None:
        if self._pending is not None and self._clock() - self._pending[2] >= 60:
            self._pending = None
            self._denials += 1

    def _enrol(self, body: bytes) -> Reply:
        if not self._token("enrol", 2):
            return _error(429, "rate")
        label, key = proto.parse_enrol(body)
        self._expire()
        if self._pc is not None:
            status, state = 409, "enrolled"
        elif self._denials >= 3:
            status, state = 403, "closed"
        elif self._pending is not None and (
            not hmac.compare_digest(self._pending[1], key) or self._pending[0] != label
        ):
            status, state = 409, "busy"
        else:
            if self._pending is None:
                self._pending = (label, key, self._clock())
            status, state = 202, "pending"
        return Reply(status, (), proto.dumps({"state": state}))

    def _matches_pending(self, code: object) -> bool:
        """Check the displayed code under the state lock without changing state."""
        if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
            return False
        if self._pending is None:
            return False
        label, key, since = self._pending
        return hmac.compare_digest(code, proto.code(label, key)) and self._clock() - since < 60

    def allow(self, code: object) -> bool:
        """Persist only the matching pending PC in one atomic mode-0600 write."""
        with self._changed:
            if not self._matches_pending(code):
                return False
            label, key, _ = self._pending
            if self._pairing_sweep_pending:
                self._store.sweep_temps("gpu-link-pc.json")
                self._pairing_sweep_pending = False
            if self._ending_answer is not None or self._ending_extra or self._pc is None or self._pc[1] != key:
                self._end_pc_answer()
            self._store.write_json("gpu-link-pc.json", {"label": label, "key": key.hex()}, durable=True)
            if self._pc is not None and self._pc[1] != key:
                self._poll += 1
            if self._pc is None or self._pc[1] != key:
                self._status = self._last_status = self._lead_label = None
                self._advertised.clear()
                self._extra_status.clear()
                self._extra_last_status.clear()
            self._epoch = self._rand(16)
            self._nonces.clear()
            self._pc = label, key
            self._pending = None
            self._changed.notify_all()
            return True

    def deny(self, code: object) -> bool:
        """Discard only the matching pending enrolment and count a refusal."""
        with self._lock:
            if not self._matches_pending(code):
                return False
            self._pending = None
            self._denials += 1
            return True

    def reopen(self) -> None:
        """Clear the three-refusal gate without extending a pending request."""
        with self._lock:
            self._denials = 0

    def _get_lease(self, pane: str) -> dict | None:
        return self._lease if pane == "gpu" else self._extra_leases[pane]

    def _set_lease(self, pane: str, lease: dict | None) -> None:
        if pane == "gpu":
            self._lease = lease
        else:
            self._extra_leases[pane] = lease

    def _advertise(self, models: list[dict]) -> Reply:
        """Bind ordered extra model IDs to stable lanes for this enrolled PC."""
        if not self._token("advertise", 4):
            return _error(429, "rate")
        updated = {f"g{index}": deepcopy(model) for index, model in enumerate(models, 1)}
        for pane, old in self._advertised.items():
            if pane not in updated or updated[pane]["id"] != old["id"]:
                if self._get_lease(pane) is not None:
                    self._pause(pane)
                if pane in updated:
                    answer = self._answers.current(pane)
                    if answer is not None and answer["state"] in ("paused", "loading", "answering"):
                        self._answers.fail(answer["id"], "model")
                self._extra_last_status.pop(pane, None)
                self._extra_status.pop(pane, None)
        self._advertised = updated
        self._changed.notify_all()
        return Reply(200, (), proto.dumps({"accepted": len(updated)}))

    def forget(self, expected_id: str | None = None) -> bool:
        """End handed-out work and remove its PC, retaining failed endings for retry."""
        with self._changed:
            if expected_id is not None and (self._pc is None or expected_id != proto.pc_id(self._pc[1])):
                return False
            self._pairing_sweep_pending = True
            self._store.sweep_temps("gpu-link-pc.json")
            self._pairing_sweep_pending = False
            if self._pc is None:
                return False
            try:
                self._end_pc_answer()
            except DurabilityError:
                raise
            except Exception:
                # Revoke the PC now; tick retries cancellation before any new offer.
                for pane in ("gpu", *self._extra_leases):
                    lease = self._get_lease(pane)
                    if lease is not None:
                        lease["failed"] = True
            self._store.write_json("gpu-link-pc.json", {}, durable=True)
            self._pc = self._status = self._last_status = None
            self._lead_label = None
            self._advertised.clear()
            self._extra_status.clear()
            self._extra_last_status.clear()
            self._history.clear()
            self._epoch = self._rand(16)
            self._nonces.clear()
            self._buckets.pop("text", None)
            self._poll += 1
            self._changed.notify_all()
            return True

    def _end_pc_answer(self) -> None:
        """Cancel handed-out PC work on every lane, leaving untouched queues."""
        for pane in ("gpu", *self._extra_leases):
            pending = self._ending_answer if pane == "gpu" else self._ending_extra.get(pane)
            answer = self._answers.get(pending) if pending is not None else self._answers.current(pane)
            if answer is not None and answer["state"] not in answers_api.FINAL:
                if answer["state"] in ("paused", "loading", "answering") or answer["text"] or answer["where"]:
                    if pane == "gpu":
                        self._ending_answer = answer["id"]
                    else:
                        self._ending_extra[pane] = answer["id"]
                    self.cancel(answer["id"])
            self._set_lease(pane, None)
            if pane == "gpu":
                self._ending_answer = None
            else:
                self._ending_extra.pop(pane, None)

    def _remember(self, lease: bytes, state: str, post: dict | None = None, acked: int | None = None) -> None:
        if self._pc is None:
            return
        self._history[lease] = (state, post, acked, hashlib.sha256(self._pc[1]).digest())
        while len(self._history) > HISTORY_LIMIT:
            self._history.popitem(last=False)

    def cancel(self, answer_id: str) -> dict:
        """Drop this answer's lease before cancelling; restore it on write failure."""
        with self._changed:
            pane = next((pane for pane in ("gpu", *self._extra_leases)
                         if (self._get_lease(pane) or {}).get("answer") == answer_id), None)
            old = self._get_lease(pane) if pane is not None else None
            matching = old is not None
            if matching:
                self._set_lease(pane, None)
            try:
                answer = self._answers.cancel(answer_id)
                self._clear_storage_fault(answer_id)
            except Exception:
                self._storage_fault = answer_id
                if matching:
                    self._set_lease(pane, old)
                raise
            if matching:
                self._remember(old["id"], "cancelled")
            self._changed.notify_all()
            return answer

    def _pause(self, pane: str = "gpu") -> None:
        old = self._get_lease(pane)
        self._set_lease(pane, None)
        if old is not None:
            try:
                self._answers.pause(old["answer"])
                self._clear_storage_fault(old["answer"])
            except answers_api.StateError:
                # The answer already left loading/answering outside this service.
                pass
            except Exception:
                self._storage_fault = old["answer"]
                self._set_lease(pane, old)
                raise
            self._changed.notify_all()

    def _status_lead_label(self, status: dict, proto_version: int) -> str | None:
        """The lead label this status leaves in force (see _record_status)."""
        if "lead_label" in status or proto_version < 2:
            return status.get("lead_label")
        return self._lead_label

    def _record_status(self, status: dict, pane: str = "gpu", *, proto_version: int = 1) -> Reply:
        if pane != "gpu" and pane not in self._advertised:
            return _error(400, "request")
        lease = self._get_lease(pane)
        live = lease if lease is None or not lease["failed"] else None
        misses = 0
        if live is not None:
            if status["lease"] == live["id"]:
                if status["state"] == "error":
                    self._set_lease(pane, None)
                    try:
                        self._answers.fail(live["answer"], status["error"])
                        self._clear_storage_fault(live["answer"])
                    except (OSError, answers_api.AnswerError):
                        self._set_lease(pane, live)
                        raise
                values = {key: status[key] for key in ("tokens", "tps") if status[key] is not None}
                if values:
                    speed = self._speed if pane == "gpu" else self._extra_speeds.get(pane)
                    if speed is None or speed["answer"] != live["answer"]:
                        speed = {"answer": live["answer"], "values": {}, "noted": None}
                        if pane == "gpu":
                            self._speed = speed
                        else:
                            self._extra_speeds[pane] = speed
                    values.update(model=(self._status_lead_label(status, proto_version) or self._model["name"])
                                  if pane == "gpu" else self._advertised[pane]["label"],
                                  where=self._pc[0])
                    speed["values"].update(values)
                    self._note_speed(live["answer"], pane=pane)
            elif live["sent"] is not None:
                misses = live["misses"] + 1
                if misses >= 2:
                    self._pause(pane)
        if self._get_lease(pane) is not None:
            self._get_lease(pane)["misses"] = misses
        if pane == "gpu":
            self._status = status
            self._last_status = self._clock()
        else:
            self._extra_status[pane] = status
            self._extra_last_status[pane] = self._clock()
        history = self._history.get(status["lease"])
        if history is not None and history[3] != hashlib.sha256(self._pc[1]).digest():
            history = None
        if status["lease"] is not None and history is None and (live is None or status["lease"] != live["id"]):
            return _error(404, "lease")
        if pane == "gpu":
            # A legacy (v1) companion never sends the field, so its omission clears an
            # obsolete label. A v2 companion omits it only on the first status after each
            # hello, before this reply confirms support, and sends it (or an explicit null)
            # one second later. Keep the label across that gap so the PC card never blinks
            # to a bare connection line on every replug or companion restart.
            # This is volatile display metadata, scoped to the enrolled PC.
            self._lead_label = self._status_lead_label(status, proto_version)
            if live is not None and self._speed is not None and self._speed["answer"] == live["answer"]:
                self._speed["values"].update(model=self._lead_label or self._model["name"], where=self._pc[0])
                self._note_speed(live["answer"])
        cancel = status["lease"] if history is not None and history[0] == "cancelled" else None
        return Reply(200, (), proto.status_reply(cancel, proto_version=proto_version))

    def _note_speed(self, answer_id: str, final: bool = False, pane: str = "gpu") -> None:
        speed = self._speed if pane == "gpu" else self._extra_speeds.get(pane)
        if speed is None or speed["answer"] != answer_id:
            return
        now = self._clock()
        if not final and speed["noted"] is not None and now - speed["noted"] < 1:
            return
        try:
            answer = self._answers.get(answer_id)
            if answer is None or all(answer.get(key) == value for key, value in speed["values"].items()):
                return
            self._answers.note(answer_id, **speed["values"])
        except (OSError, answers_api.AnswerError):
            # Display metadata is best effort; retain it for the next attempt.
            return
        if any(key in speed["values"] for key in ("tokens", "tps")):
            speed["noted"] = now

    def _work(self, wait: int, pane: str = "gpu") -> Reply:
        if pane == "gpu":
            self._poll += 1
            generation = self._poll
        else:
            self._extra_polls[pane] += 1
            generation = self._extra_polls[pane]
        self._changed.notify_all()
        deadline = time.monotonic() + wait
        logical_deadline = self._clock() + wait
        while not self._closed and generation == (self._poll if pane == "gpu" else self._extra_polls[pane]) and self._pc is not None:
            if pane == "gpu":
                self._check_model()
            if (pane == "gpu" and self._model["state"] == "ready") or (pane != "gpu" and pane in self._advertised):
                reply = self._offer(pane)
                if reply is not None:
                    return reply
            remaining = min(deadline - time.monotonic(), logical_deadline - self._clock())
            if remaining <= 0:
                break
            self._changed.wait(min(0.1, remaining))
        return Reply(204)

    def _offer(self, pane: str = "gpu") -> Reply | None:
        if self._ending_answer is not None or self._ending_extra:
            self._end_pc_answer()
        old = self._get_lease(pane)
        model_id = self._model_hash if pane == "gpu" else self._advertised[pane]["id"]
        if old is not None:
            answer = self._answers.get(old["answer"])
            if answer is None or answer["state"] not in ("loading", "answering") or old["model"] != model_id:
                return _error(400, "request")
        else:
            answer = self._answers.current(pane)
            if answer is None:
                return None
            if answer["state"] in ("loading", "answering"):
                answer = self._answers.pause(answer["id"])
                self._clear_storage_fault(answer["id"])
            if answer["state"] not in ("waiting", "paused"):
                return _error(400, "request")
        lease = self._rand(16)
        body = (proto.work_reply(lease, model_id, answer["question"], answer["text"])
                if pane == "gpu" else proto.extra_work_reply(lease, model_id, answer["question"], answer["text"]))
        if old is None:
            self._answers.begin(answer["id"])
            self._clear_storage_fault(answer["id"])
        self._set_lease(pane, {
            "id": lease,
            "answer": answer["id"],
            "sent": None,
            "failed": False,
            "misses": 0,
            "model": model_id,
        })
        speed = self._speed if pane == "gpu" else self._extra_speeds.get(pane)
        if speed is None or speed["answer"] != answer["id"]:
            speed = {"answer": answer["id"], "values": {}, "noted": None}
            if pane == "gpu":
                self._speed = speed
            else:
                self._extra_speeds[pane] = speed
        speed["values"].update(model=(self._lead_label or self._model["name"]) if pane == "gpu" else self._advertised[pane]["label"],
                               where=self._pc[0])
        self._note_speed(answer["id"], pane=pane)
        return self._work_reply(body, pane)

    def _work_reply(self, body: bytes, pane: str = "gpu") -> Reply:
        live = self._get_lease(pane)
        completed = False

        def delivered(success: bool) -> None:
            nonlocal completed
            with self._changed:
                if completed or self._get_lease(pane) is not live:
                    return
                completed = True
                if success:
                    live.update(sent=self._clock(), misses=0)
                else:
                    live["failed"] = True
                    try:
                        self._pause(pane)
                    except (OSError, answers_api.StateError):
                        # A failed durable pause is retried by tick, even unsent.
                        return

        return Reply(200, (), body, sent=lambda: delivered(True), failed=lambda: delivered(False))

    def _text(self, lease: bytes, body: bytes) -> Reply:
        if not self._token("text", 4):
            return _error(429, "rate")
        post = proto.parse_text(body)
        pane = next((pane for pane in ("gpu", *self._extra_leases)
                     if (self._get_lease(pane) or {}).get("id") == lease), None)
        live = self._get_lease(pane) if pane is not None else None
        if live is not None and live["failed"]:
            live = None
        history = self._history.get(lease)
        if history is not None and history[3] != hashlib.sha256(self._pc[1]).digest():
            history = None
        if live is not None and live["id"] == lease:
            answer_id = live["answer"]
        elif history is not None and history[0] == "done" and post == history[1]:
            return Reply(200, (), proto.text_reply(history[2]))
        else:
            return _error(404, "lease")
        if post["done"] and live is not None and live["id"] == lease:
            self._set_lease(pane, None)
        stored_bytes = self._answers.get(answer_id)["bytes"]
        try:
            answer = self._answers.append(answer_id, **post)
        except (OSError, answers_api.AnswerError) as err:
            if live is not None:
                self._set_lease(pane, live)
            if isinstance(err, answers_api.OffsetError):
                return Reply(409, (), proto.stored_reply(err.stored))
            if isinstance(err, answers_api.TooLongError):
                return Reply(413, (), proto.stored_reply(err.stored))
            if isinstance(err, answers_api.TextError):
                return _error(400, "text")
            raise
        # Retry metadata without requiring optional speed fields from the PC.
        self._note_speed(answer_id, final=post["done"], pane=pane)
        if answer["bytes"] > stored_bytes or answer["state"] in answers_api.FINAL:
            self._clear_storage_fault(answer_id)
        if post["done"]:
            self._remember(lease, "done", post, answer["bytes"])
        self._changed.notify_all()
        return Reply(200, (), proto.text_reply(answer["bytes"]))

    def tick(self) -> None:
        """Expire enrolment and pause silent work; storage failures retry next tick."""
        with self._changed:
            if self._closed:
                return
            self._expire()
            if self._ending_answer is not None or self._ending_extra:
                try:
                    self._end_pc_answer()
                except OSError:
                    self._storage_fault = self._ending_answer or ""
                    return
            for pane in ("gpu", *self._extra_leases):
                lease = self._get_lease(pane)
                if pane != "gpu" and pane not in self._advertised and lease is None:
                    continue
                if lease is not None:
                    last = lease["sent"]
                    status_at = self._last_status if pane == "gpu" else self._extra_last_status.get(pane)
                    if last is not None and status_at is not None:
                        last = max(last, status_at)
                    model_id = self._model_hash if pane == "gpu" else self._advertised.get(pane, {}).get("id")
                    stale = model_id is not None and lease["model"] != model_id
                    if lease["failed"] or stale or (last is not None and self._clock() - last >= LINK_SECONDS):
                        try:
                            self._pause(pane)
                        except (OSError, answers_api.StateError):
                            # Retain this lease for a durable retry, but still pause the others.
                            continue
                else:
                    answer = None
                    try:
                        answer = self._answers.current(pane)
                        if answer is not None and answer["state"] in ("loading", "answering"):
                            self._answers.pause(answer["id"])
                            self._clear_storage_fault(answer["id"])
                    except OSError:
                        self._storage_fault = answer["id"] if answer is not None else ""
                    except answers_api.StateError:
                        pass
            try:
                self._check_model()
            except OSError:
                # A cache read failed. Retry on the next tick without publishing it.
                return

    def _clear_storage_fault(self, answer_id: str) -> None:
        if self._storage_fault == answer_id:
            self._storage_fault = None

    def snapshot(self) -> dict:
        """Return copies of display-only data, never keys, nonces or leases."""
        with self._lock:
            if self._storage_fault:
                answer = self._answers.get(self._storage_fault)
                if answer is None or answer["state"] in answers_api.FINAL:
                    self._storage_fault = None
            pending = None
            if self._pending is not None:
                label, key, since = self._pending
                pending = {
                    "label": display_label(label),
                    "code": proto.code(label, key),
                    "seconds": max(0, math.ceil(60 - (self._clock() - since))),
                }
            pc = None
            if self._pc is not None:
                status = self._status or {}
                pc = {name: deepcopy(status.get(name)) for name in ("state", "gpu", "copied", "total", "error")}
                now = self._clock()
                models = []
                for pane in self._extra_leases:
                    model = self._advertised.get(pane)
                    if model is None:
                        answer = self._answers.current(pane)
                        if answer is None:
                            continue
                        model = {"id": "", "label": answer["model"], "maker": "", "gpu": None}
                    lane_status = self._extra_status.get(pane, {})
                    models.append({"pane": pane, **deepcopy(model),
                                   "live": pane in self._advertised and
                                   now - self._extra_last_status.get(pane, -float("inf")) < LINK_SECONDS and
                                   lane_status.get("state") != "error"})
                    models[-1]["live_speed"] = lane_status.get("tps")
                pc.update(
                    id=proto.pc_id(self._pc[1]),
                    label=display_label(self._pc[0]),
                    main_live=self._last_status is not None and now - self._last_status < LINK_SECONDS,
                    live=(self._last_status is not None and now - self._last_status < LINK_SECONDS)
                    or any(now - when < LINK_SECONDS for when in self._extra_last_status.values()),
                    models=models,
                )
                if self._lead_label is not None:
                    pc["lead_label"] = self._lead_label
            return {
                "storage": "error" if self._storage_fault is not None or self._answers.startup_notice else None,
                "storage_notice": self._answers.startup_notice,
                "storage_fault": self._storage_fault is not None,
                "model": self._model.copy(),
                "pc": pc,
                "pending": pending,
                "enrol": "closed" if self._denials >= 3 else "open",
            }

    def _check_model(self) -> None:
        if self._model_path is None or self._closed:
            return
        try:
            identity = _identity(self._model_path)
        except OSError:
            self._model["state"] = "error"
            return
        if self._model_id == identity and self._model["state"] == "ready":
            return
        if self._hasher is not None and self._hasher.is_alive():
            self._model.update(state="checking", size=identity["size"])
            return
        if self._hash_failure is not None:
            failed_identity, retry_at = self._hash_failure
            if failed_identity == identity and self._clock() < retry_at:
                self._model["state"] = "error"
                return
        # A Store failure propagates to handle as signed 500 before state changes.
        cached, _ = self._store.read_json("gpu-link-model.json", {})
        self._model.update(state="checking", size=identity["size"])
        if cached.get("identity") == identity and proto.unhex(cached.get("sha256"), 32) is not None:
            self._model_id, self._model_hash = identity, cached["sha256"]
            self._model["state"] = "ready"
            return
        thread = threading.Thread(target=self._hash_model, args=(identity,), name="gpu-link-hash")
        thread.start()
        self._hasher = thread

    def _hash_model(self, identity: dict) -> None:
        try:
            digest = hashlib.sha256()
            with self._model_path.open("rb") as stream:
                while not self._hash_stop.is_set():
                    chunk = stream.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
            with self._changed:
                if self._closed or _identity(self._model_path) != identity:
                    return
                value = digest.hexdigest()
                self._model_id, self._model_hash = identity, value
                self._hash_failure = None
                self._model.update(state="ready", size=identity["size"])
                self._changed.notify_all()
                try:
                    self._store.write_json("gpu-link-model.json", {"identity": identity, "sha256": value})
                except OSError:
                    # Readiness depends on the digest; the restart cache is best effort.
                    pass
        except OSError:
            with self._lock:
                self._model["state"] = "error"
                self._hash_failure = identity, self._clock() + HASH_RETRY_SECONDS

    def _model_reply(self, value: str, range_value: str | None) -> Reply:
        self._check_model()
        if self._model["state"] != "ready" or value != self._model_hash:
            return _error(404, "model")
        size = self._model["size"]
        if range_value is None:
            return Reply(
                200,
                (),
                file=(self._model_path, 0, size),
                file_identity=self._model_id.copy(),
                file_error=_error(500, "state"),
            )
        try:
            start, end = proto.parse_range(range_value, size)
        except proto.ProtoError:
            return _error(416, "range")
        return Reply(
            206,
            (("Content-Range", proto.content_range(start, end, size)),),
            file=(self._model_path, start, end - start + 1),
            file_identity=self._model_id.copy(),
            file_error=_error(500, "state"),
        )

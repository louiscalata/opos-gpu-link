# SPDX-License-Identifier: Apache-2.0
"""Show-day model health and recovery, restricted to companion-owned servers."""
from __future__ import annotations

import argparse
import collections
import errno
import hashlib
import http.client
import json
import math
import os
import platform
import re
import secrets
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class Model:
    """An inventory snapshot. ``available`` means already verified on local disk.

    Fallback selection never stats files or downloads. The caller supplies the
    snapshot and must verify/load the returned candidate before advertising it.
    ``size`` is the complete model file size in bytes, not rounded MiB.
    """

    name: str
    size: int
    path: Path | None = None
    family: str = ""
    sha256: str | None = None
    known_good: bool = True
    available: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("model name must be non-empty")
        if isinstance(self.size, bool) or not isinstance(self.size, int) or self.size <= 0:
            raise ValueError("model file size must be a positive byte count")
        if self.path is not None:
            object.__setattr__(self, "path", Path(self.path))


def _model_family(model: Model) -> str:
    if model.family.strip():
        return model.family.strip().casefold()
    name = model.name.casefold()
    for family in ("gemma", "qwen", "llama", "mistral", "phi", "lfm", "smollm",
                   "granite", "deepseek", "glm"):
        if family in name:
            return family
    return ""


def _same_model(left: Model, right: Model) -> bool:
    return (left.name.strip().casefold() == right.name.strip().casefold()
            or (left.path is not None and right.path is not None and left.path == right.path)
            or (bool(left.sha256) and left.sha256 == right.sha256))


def _last_resort(model: Model) -> bool:
    return bool(re.search(r"gemma[\s_.-]*3[\s_.-]*1b(?:\b|_)", model.name, re.I))


class FallbackPlan:
    """Two failures per lane/question permit one smaller-model swap per show.

    Local inventory entries must be marked ``available``; absent candidates may
    come only from the caller's pinned, known-good catalog and only when online.
    Returning a candidate consumes the lane's sole swap, even if loading fails.
    Use a new plan for a new show. No filesystem, process or network operations
    occur here, so this policy can be exercised with inventory snapshots alone.
    """

    def __init__(self, models: Iterable[Model], catalog: Iterable[Model] = (),
                 offline: bool = True) -> None:
        self.models = tuple(models)
        self.catalog = tuple(catalog)
        self.offline = offline
        self._failures: dict[tuple[str, str], int] = {}
        self._swapped: dict[str, Model] = {}
        self._status: dict[str, str] = {}
        self._lock = threading.Lock()

    def failure_count(self, lane: str, question: str) -> int:
        with self._lock:
            return self._failures.get((lane, question), 0)

    def status(self, lane: str) -> str:
        """``ready``, ``retry``, ``no_fallback``, ``swapped`` or ``fallback_failed``."""
        with self._lock:
            return self._status.get(lane, "ready")

    def record_failure(self, lane: str, question: str, original: Model,
                       reason: str) -> tuple[Model, str] | None:
        """Count one failed attempt and return an honest replacement offer, if any.

        ``original`` is the currently failing model. Every failure after a swap
        is reported as ``fallback_failed`` and cannot trigger another swap,
        including on a later question. Failure reasons are lane-layer strings
        such as ``garbled``, ``stream_error``, ``model_start`` and ``crash``.
        """
        if not isinstance(lane, str) or not lane:
            raise ValueError("lane must be non-empty")
        if not isinstance(question, str):
            raise ValueError("question must be a string")
        if not isinstance(reason, str) or not reason:
            raise ValueError("failure reason must be non-empty")
        with self._lock:
            key = lane, question
            self._failures[key] = count = self._failures.get(key, 0) + 1
            if lane in self._swapped:
                self._status[lane] = "fallback_failed"
                return None
            if count < 2:
                self._status[lane] = "retry"
                return None
            candidates = [m for m in self.models if m.available]
            candidates.extend(m for m in self.catalog if m.available or not self.offline)
            candidates = [m for m in candidates
                          if m.known_good and m.size < original.size
                          and not _same_model(m, original)]
            if not candidates:
                self._status[lane] = "no_fallback"
                return None
            family = _model_family(original)
            # Gemma 3 1B is the final resort even for an original Gemma model.
            # Within each group favor a local file, then the closest smaller size.
            candidate = min(candidates, key=lambda m: (
                _last_resort(m), not (family and _model_family(m) == family),
                not m.available, -m.size, m.name.casefold()))
            self._swapped[lane] = candidate
            self._status[lane] = "swapped"
            return candidate, f"{candidate.name} (fallback for {original.name})"

# A watchdog owns process objects, never PID-only handles. No process discovery.

WATCHDOG_ENV = 'OPOS_GPU_LINK_WATCHDOG'
PROTECTED_PORTS = frozenset({1234, 1235, 1236, 1237, 8765, 8767, 11434, 41484,
                             56795, 56740, 24001})
PROTECTED_PIDS = frozenset({41484, 10188, 24001})


def watchdog_enabled(environ=None) -> bool:
    return (os.environ if environ is None else environ).get(WATCHDOG_ENV, '1') != '0'


def safe_port(port: int) -> bool:
    return isinstance(port, int) and not isinstance(port, bool) and 38400 <= port <= 38499 and port not in PROTECTED_PORTS


def _allowed_port(port: int, allowed_ports: frozenset[int] | None = None) -> bool:
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535 or port in PROTECTED_PORTS:
        return False
    return safe_port(port) if allowed_ports is None else port in allowed_ports


def port_available(port: int, *, allowed_ports: frozenset[int] | None = None) -> bool:
    """Bind-only check: never connect to a foreign listener, even for discovery."""
    if not _allowed_port(port, allowed_ports):
        return False
    addresses = [(socket.AF_INET, '127.0.0.1')]
    if socket.has_ipv6:
        addresses.append((socket.AF_INET6, '::1'))
    for family, address in addresses:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as probe:
                if os.name != 'nt':
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                probe.bind((address, port))
        except OSError as error:
            if family == socket.AF_INET6 and error.errno in {errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT, errno.EADDRNOTAVAIL}:
                continue
            return False
    return True


@contextmanager
def _http_deadline(port: int, timeout: float, *, allowed_ports: frozenset[int] | None = None):
    """Interrupt even a slow-dripping response at an absolute wall deadline."""
    if not _allowed_port(port, allowed_ports) or timeout <= 0:
        raise ValueError('HTTP requires an explicitly owned port and a positive timeout')
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=timeout)
    expired = threading.Event()
    request_socket = None
    def interrupt():
        expired.set()
        if request_socket is not None:
            try:
                # A closing HTTP response may detach connection.sock while its
                # buffered reader still owns the original connected socket.
                request_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    timer = threading.Timer(timeout, interrupt)
    timer.daemon = True
    timer.start()
    try:
        connection.connect()
        request_socket = connection.sock
        if expired.is_set():
            raise TimeoutError('HTTP deadline expired')
        yield connection
        if expired.is_set():
            raise TimeoutError('HTTP deadline expired')
    finally:
        timer.cancel()
        connection.close()


def server_healthy(port: int, timeout: float = 2.0, *, allowed_ports: frozenset[int] | None = None) -> bool:
    if not _allowed_port(port, allowed_ports):
        return False
    try:
        with _http_deadline(port, timeout, allowed_ports=allowed_ports) as connection:
            connection.request('GET', '/health')
            response = connection.getresponse()
            response.read(1024)
            return response.status == 200
    except (OSError, http.client.HTTPException):
        return False


@dataclass
class WatchedServer:
    process: Any
    port: int
    command: tuple[str, ...]
    options: dict = field(default_factory=dict, repr=False)
    target: Any = field(default=None, repr=False)
    pid: int = 0
    misses: int = 0
    next_restart: float | None = None
    ready_after: float = 0
    attempts: Any = field(default_factory=collections.deque)
    gave_up: bool = False


class Watchdog:
    """Tick-driven supervisor; only tracked Popen identities may be stopped.

    spawn() records a process created by our factory. Runtime adoption accepts
    only real child Popen objects from Runtime.servers, never a bare PID. Keep
    env/cwd and the private key-file restart factory in the owning runtime;
    commands and environment are never included in events or receipts.
    """

    def __init__(self, runtime=None, *, process_factory=subprocess.Popen,
                 clock=time.monotonic, health=server_healthy, free=port_available,
                 notify: Callable[[dict], None] | None = None,
                 backoff: float = 1.0, startup_grace: float = 10.0,
                 enabled: bool | None = None, spawn_options: dict | None = None,
                 allowed_ports: Iterable[int] | None = None):
        self.runtime = runtime
        self.process_factory, self.clock = process_factory, clock
        # A production launcher may authorize only its already-created slots.
        # The standalone preflight/watch defaults and spawn() stay D-only.
        runtime_ports = frozenset(allowed_ports or ())
        if any(not _allowed_port(port, runtime_ports) for port in runtime_ports):
            raise ValueError('Protected or invalid runtime port')
        if runtime_ports and (runtime is None or getattr(runtime, 'existing', False)
                              or not runtime_ports.issubset(s.port for s in runtime.servers)):
            raise ValueError('Expanded ports require companion-owned runtime slots')
        self._allowed_ports = frozenset(range(38400, 38500)) | runtime_ports
        self.health = ((lambda port: server_healthy(port, allowed_ports=self._allowed_ports))
                       if health is server_healthy else health)
        self.free = ((lambda port: port_available(port, allowed_ports=self._allowed_ports))
                     if free is port_available else free)
        self.notify = notify or (lambda event: None)
        self.backoff, self.startup_grace = max(0.0, backoff), max(0.0, startup_grace)
        self.enabled = watchdog_enabled() if enabled is None else enabled
        self.servers: list[WatchedServer] = []
        self._owned: dict[int, Any] = {}
        if runtime is not None and self.enabled:
            if getattr(runtime, 'existing', False):
                raise ValueError('Existing or discovered servers cannot be adopted')
            # Popen does not retain env/cwd/redirection kwargs. Requiring the
            # owning launcher to supply them avoids a silently different restart.
            if any(s.port not in (spawn_options or {}) for s in runtime.servers):
                raise ValueError('Runtime adoption requires captured spawn_options for every server')
            for server in runtime.servers:
                self.adopt(server, (spawn_options or {})[server.port])

    def _validate_command(self, command, port):
        if not _allowed_port(port, self._allowed_ports):
            raise ValueError('Only unprotected D ports or explicitly owned runtime ports are allowed')
        if not command or any(not isinstance(part, str) for part in command):
            raise ValueError('An argv command is required; shell commands are refused')
        # Require explicit loopback+port, with no duplicate options overriding it.
        for flag, expected in (('--port', str(port)), ('--host', '127.0.0.1')):
            if command.count(flag) != 1 or any(p.startswith(flag + '=') for p in command):
                raise ValueError('Command must specify exactly one loopback host and matching port')
            index = command.index(flag)
            if index + 1 >= len(command) or command[index + 1] != expected:
                raise ValueError('Command must use the tracked loopback port')
        if '-p' in command or '--listen' in command:
            raise ValueError('Ambiguous listener options are refused')

    def _record(self, process, port, command, options, target=None):
        self._validate_command(command, port)
        if not isinstance(process.pid, int) or process.pid <= 0 or process.pid in PROTECTED_PIDS:
            raise ValueError('Protected or invalid process identity')
        if process.pid in self._owned or any(s.port == port for s in self.servers):
            raise ValueError('Process or port already tracked')
        watched = WatchedServer(process, port, tuple(command), options, target,
                                pid=process.pid, ready_after=self.clock() + self.startup_grace)
        self._owned[process.pid] = process
        self.servers.append(watched)
        return watched

    def spawn(self, command, port: int, **options) -> WatchedServer:
        if not safe_port(port):
            raise ValueError('New watchdog launches are restricted to D ports 38400-38499')
        self._validate_command(command, port)
        if any(server.port == port for server in self.servers) or not self.free(port):
            raise ValueError('Port is already listening or unavailable; no server started')
        options = dict(options)
        if options.get('shell') or options.get('preexec_fn') is not None:
            raise ValueError('Unsafe process options')
        options.setdefault('stdout', subprocess.DEVNULL)
        options.setdefault('stderr', subprocess.DEVNULL)
        process = self.process_factory(list(command), **options)
        return self._record(process, port, tuple(command), options)

    def adopt(self, target, options: dict) -> WatchedServer:
        """Register a launcher-created replacement. Serialize with tick/release.

        Expansion authorizes a fixed set of startup slots, never discovered
        servers or new production ports. The runtime retains child ownership.
        """
        if (self.runtime is None or getattr(self.runtime, 'existing', False)
                or not any(target is server for server in self.runtime.servers)):
            raise ValueError('Target is not a companion-owned runtime slot')
        process = target.process
        if not isinstance(process, subprocess.Popen) or not getattr(process, '_child_created', False):
            raise ValueError('Runtime server must hold our child Popen, never a PID')
        command = tuple(str(part) for part in process.args) if isinstance(process.args, (list, tuple)) else ()
        if '--api-key-file' in command and self.process_factory is subprocess.Popen:
            raise ValueError('Authenticated Runtime restart requires a private-key recreating process_factory')
        return self._record(process, target.port, command, dict(options), target)

    def release(self, target) -> WatchedServer:
        """Forget a still-owned slot before the launcher replaces it; no signal."""
        server = next((item for item in self.servers if item.target is target), None)
        if server is None or not self.owns(server):
            raise ValueError('Refusing to release a process we do not own')
        self.servers.remove(server)
        self._owned.pop(server.pid, None)
        return server

    def owns(self, server: WatchedServer) -> bool:
        return (any(server is tracked for tracked in self.servers)
                and server.process is self._owned.get(server.pid)
                and server.process.pid == server.pid and server.pid not in PROTECTED_PIDS
                and (server.target is None or (self.runtime is not None
                     and any(server.target is item for item in self.runtime.servers)
                     and server.target.process is server.process)))

    def _event(self, server, status):
        event = {'port': server.port, 'status': status, 'restarts': len(server.attempts)}
        try:
            self.notify(event)
        except Exception:
            # A UI callback must not interrupt process ownership/cleanup bookkeeping.
            pass
        return event

    def stop(self, server: WatchedServer):
        if not self.owns(server):
            raise ValueError('Refusing to signal a process we do not own')
        if server.process.poll() is None:
            try:
                server.process.terminate()
            except ProcessLookupError:
                return
            try:
                server.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                server.process.kill()
                server.process.wait(timeout=3)

    def close(self):
        self.enabled = False
        refused = False
        stop_error = None
        for server in self.servers:
            if self.owns(server):
                try:
                    self.stop(server)
                except (OSError, subprocess.SubprocessError) as error:
                    stop_error = error
            else:
                refused = True
                self._event(server, 'ownership_refused')
        if refused:
            raise ValueError('Foreign process refused; other owned servers were stopped')
        if stop_error is not None:
            raise stop_error

    def tick(self) -> list[dict]:
        if not self.enabled:
            return []
        events = []
        for server in self.servers:
            if server.gave_up:
                continue
            if not self.owns(server) or not _allowed_port(server.port, self._allowed_ports):
                server.gave_up = True
                events.append(self._event(server, 'ownership_refused'))
                continue
            now = self.clock()
            while server.attempts and now - server.attempts[0] >= 600:
                server.attempts.popleft()
            if server.next_restart is None:
                exited = server.process.poll() is not None
                if not exited:
                    if now < server.ready_after:
                        continue
                    try:
                        healthy = self.health(server.port)
                    except (OSError, ValueError, http.client.HTTPException):
                        healthy = False
                    server.misses = 0 if healthy else server.misses + 1
                    if server.misses < 3:
                        continue
                server.next_restart = now + self.backoff * (2 ** len(server.attempts))
                events.append(self._event(server, 'restart_pending'))
            if now < server.next_restart:
                continue
            if len(server.attempts) >= 3:
                server.gave_up = True
                events.append(self._event(server, 'gave_up'))
                continue
            # Signal only the owned Popen. If someone else took the port after
            # exit, leave their listener alone and stop supervising this slot.
            self.stop(server)
            if not self.free(server.port):
                server.gave_up = True
                events.append(self._event(server, 'port_busy'))
                continue
            server.attempts.append(now)  # unsuccessful spawn attempts count too
            old_pid = server.pid
            try:
                self._validate_command(server.command, server.port)
                if server.options.get('shell') or server.options.get('preexec_fn') is not None:
                    raise ValueError('Unsafe process options')
                process = self.process_factory(list(server.command), **server.options)
            except (OSError, ValueError, subprocess.SubprocessError):
                server.next_restart = now + self.backoff * (2 ** len(server.attempts))
                events.append(self._event(server, 'restart_failed'))
                continue
            if not isinstance(process.pid, int) or process.pid <= 0 or process.pid in PROTECTED_PIDS or process.pid in self._owned:
                server.gave_up = True
                events.append(self._event(server, 'ownership_refused'))
                continue
            self._owned.pop(old_pid, None)
            self._owned[process.pid] = process
            server.process, server.pid = process, process.pid
            if server.target is not None:
                server.target.process = process
            server.misses, server.next_restart = 0, None
            server.ready_after = now + self.startup_grace
            events.append(self._event(server, 'restarted'))
        return events

# Pre-show health checks. All launches are local, explicit and disposable.


PREFLIGHT_PORTS = range(38400, 38500)
MEMORY_WARN_PERCENT = 15.0
MEMORY_FAIL_PERCENT = 5.0
DISK_WARN_BYTES = 256 * 1024 * 1024
DISK_FAIL_BYTES = 64 * 1024 * 1024


def headroom(total: int, free: int, source: str) -> dict:
    """Classify measured headroom; unknown must never become a measured pass."""
    if total <= 0 or free < 0 or free > total:
        return {"status": "UNKNOWN", "source": source, "free_percent": None}
    percent = free * 100.0 / total
    status = "FAIL" if percent < MEMORY_FAIL_PERCENT else "WARN" if percent < MEMORY_WARN_PERCENT else "PASS"
    return {"status": status, "source": source, "total_bytes": total,
            "free_bytes": free, "free_percent": round(percent, 2)}


def memory_headroom(backend: str = "cpu", *, runner=subprocess.run,
                    system: str | None = None, sysfs: Path = Path("/sys/class/drm")) -> dict:
    """Read counters only. Dedicated VRAM and unified RAM are labelled distinctly."""
    def output(command):
        try:
            result = runner(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            timeout=5, check=False)
            return result.stdout.decode("utf-8", "replace") if result.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            return ""

    if backend.lower() in {"nvidia", "cuda"}:
        rows = output(["nvidia-smi", "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"])
        measurements = []
        for line in rows.splitlines():
            try:
                total, free = (int(x.strip()) * 1024 * 1024 for x in line.split(","))
                row = headroom(total, free, "nvidia-smi VRAM")
                if row["free_percent"] is not None:
                    measurements.append(row)
            except ValueError:
                continue
        # Without an explicit device selection, report the tightest device conservatively.
        return min(measurements, key=lambda x: x["free_percent"]) if measurements else headroom(0, 0, "nvidia-smi VRAM")
    if (system or platform.system()) == "Darwin":
        try:
            total = int(output(["sysctl", "-n", "hw.memsize"]).strip())
            stats = output(["vm_stat"])
            page = int(re.search(r"page size of (\d+) bytes", stats).group(1))
            pages = {}
            for line in stats.splitlines():
                match = re.match(r"(Pages [^:]+):\s*(\d+)\.", line)
                if match:
                    pages[match.group(1)] = int(match.group(2))
            if "Pages free" not in pages:
                raise ValueError("no free-page counter")
            available = sum(pages.get(name, 0) for name in ("Pages free", "Pages inactive", "Pages speculative")) * page
            return headroom(total, available, "macOS unified/system RAM (free + inactive + speculative)")
        except (ValueError, AttributeError):
            return headroom(0, 0, "macOS unified/system RAM")
    if backend.lower() in {"amd", "rocm", "vulkan"}:
        measurements = []
        for device in sorted(sysfs.glob("card[0-9]*/device")):
            try:
                total = int((device / "mem_info_vram_total").read_text())
                used = int((device / "mem_info_vram_used").read_text())
                row = headroom(total, total - used, "amdgpu sysfs VRAM")
                if row["free_percent"] is not None:
                    measurements.append(row)
            except (OSError, ValueError):
                continue
        if measurements:
            return min(measurements, key=lambda x: x["free_percent"])
    return headroom(0, 0, "memory counter unavailable")


def preflight_port_free(port: int) -> bool:
    """Check by binding, without connecting to an existing listener."""
    return port_available(port)


def warmup_text(server, key: str, timeout: float) -> str:
    body = json.dumps({"model": getattr(server, "alias", "opos-gpu-link"), "max_tokens": 256,
                       "temperature": 0.2, "repeat_penalty": 1.1, "stream": False,
                       "messages": [{"role": "user", "content": "Explain in two sentences what a GPU does."}]})
    with _http_deadline(server.port, timeout) as connection:
        connection.request("POST", "/v1/chat/completions", body,
                           {"Content-Type": "application/json", "Authorization": "Bearer " + key})
        response = connection.getresponse()
        raw = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(raw) > 1024 * 1024:
            raise ValueError("warm-up HTTP failure or oversized response")
        content = json.loads(raw)["choices"][0]["message"].get("content")
        if not isinstance(content, str):
            raise ValueError("warm-up has no answer text")
        return content


def preflight_healthy(server, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if server.process.poll() is not None:
            return False
        try:
            if server_healthy(server.port, max(0.01, min(1.0, deadline - time.monotonic()))):
                return True
        except (OSError, http.client.HTTPException):
            pass
        time.sleep(min(0.1, max(0, deadline - time.monotonic())))
    return False


def preflight_garble_reason(text: str) -> str | None:
    try:
        from gpu_link_guard import garble_reason
    except ImportError:
        from gpu_link_e2e import degenerate_text as garble_reason
    return garble_reason(text)


class Preflight:
    """Verify configured model files and briefly load each on a server we launch.

    Injected launchers return a server with process, port, alias and stop(quiet=True).
    The launcher contract transfers ownership of that Popen to this check. Fakes can
    exercise all policy decisions without opening a socket or allocating a model.
    """
    def __init__(self, models: Iterable[Model], binary: Path | None, log_dir: Path,
                 backend: str = "cpu", offline: bool = True, timeout: float = 60,
                 port: int = 38400, *, launcher: Callable | None = None,
                 health: Callable = preflight_healthy, warmup: Callable = warmup_text,
                 memory: Callable | None = None, disk: Callable = shutil.disk_usage,
                 free: Callable = preflight_port_free, clock: Callable = time.monotonic,
                 garble: Callable = preflight_garble_reason, profile=None, device=None):
        if not safe_port(port):
            raise ValueError("preflight port must be in 38400-38499")
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        self.models, self.binary, self.log_dir = list(models), binary, Path(log_dir)
        self.backend, self.offline, self.timeout, self.port = backend, bool(offline), timeout, port
        self.launcher, self.health, self.warmup = launcher, health, warmup
        self.memory = memory or (lambda: memory_headroom(backend))
        self.disk, self.free, self.clock, self.garble = disk, free, clock, garble
        self.profile, self.device = profile, device

    def _launch(self, model, port, key_file):
        import gpu_link_autosetup as setup
        env = setup.runtime_env(self.binary)
        env = setup.moltenvk_env(env, binary=self.binary)
        return setup.launch_llama_server(self.binary, model.path, port, env, self.log_dir,
                                         self.backend, key_file, profile=self.profile, device=self.device)

    def run(self) -> dict:
        checks = [{"check": "offline", "status": "PASS", "enabled": self.offline,
                   "detail": "Downloads disabled for preflight regardless of flag"}]
        rows = []
        receipt = {"offline": self.offline, "downloads": "disabled", "checks": checks,
                   "models": rows, "memory_thresholds_percent": {"warn_below": 15, "fail_below": 5},
                   "disk_thresholds_bytes": {"warn_below": DISK_WARN_BYTES, "fail_below": DISK_FAIL_BYTES},
                   "load_scope": "individual models; concurrent all-lane memory fit is NOT_RUN"}
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            space = self.disk(self.log_dir)
            free_bytes = space.free
            checks.append({"check": "log_disk", "status": "FAIL" if free_bytes < DISK_FAIL_BYTES else
                           "WARN" if free_bytes < DISK_WARN_BYTES else "PASS", "free_bytes": free_bytes})
        except OSError:
            checks.append({"check": "log_disk", "status": "FAIL", "detail": "Log directory is unavailable"})
        checks.append(dict(self.memory(), check="memory_before_load"))
        blocked = any(row["status"] == "FAIL" for row in checks)
        if not self.models:
            checks.append({"check": "models", "status": "FAIL", "detail": "No models configured"})
        for model in self.models:
            row = {"model": model.name, "status": "FAIL", "file": "unchecked", "load": "NOT_RUN",
                   "warmup": "NOT_RUN"}
            rows.append(row)
            server = None
            try:
                if model.path is None or not Path(model.path).is_file():
                    row["file"] = "missing"
                    continue
                path = Path(model.path)
                if model.size > 0 and path.stat().st_size != model.size:
                    row["file"] = "size_mismatch"
                    continue
                if model.sha256:
                    digest = hashlib.sha256()
                    with path.open("rb") as source:
                        for chunk in iter(lambda: source.read(1024 * 1024), b""):
                            digest.update(chunk)
                    if digest.hexdigest().lower() != model.sha256.lower():
                        row["file"] = "sha256_mismatch"
                        continue
                row["file"] = "PASS"
                if blocked:
                    row["detail"] = "Memory or log disk check failed; load skipped"
                    continue
                if self.launcher is None and (self.binary is None or not Path(self.binary).is_file()):
                    row["load"] = "missing_binary"
                    continue
                # Strict port means never silently select another port or attach to a listener.
                if not self.free(self.port):
                    row["load"] = "port_occupied"
                    continue
                import gpu_link_autosetup as setup
                key = secrets.token_urlsafe(32)
                with tempfile.TemporaryDirectory(prefix="health-key-", dir=self.log_dir) as key_dir:
                    key_file = setup.write_key_file(key, Path(key_dir))
                    start = self.clock()
                    server = (self.launcher or self._launch)(model, self.port, key_file)
                    remaining = self.timeout - (self.clock() - start)
                    if remaining <= 0 or not self.health(server, remaining):
                        row["load"] = "timeout_or_crash"
                        continue
                    row["load"] = "PASS"
                    row["memory_loaded"] = self.memory()
                    if row["memory_loaded"]["status"] == "FAIL":
                        row["warmup"] = "memory_headroom_failed"
                        continue
                    remaining = self.timeout - (self.clock() - start)
                    if remaining <= 0:
                        row["warmup"] = "timeout"
                        continue
                    text = self.warmup(server, key, remaining)
                    if self.clock() - start > self.timeout:
                        row["warmup"] = "timeout"
                    elif not isinstance(text, str) or not text.strip():
                        row["warmup"] = "empty"
                    else:
                        reason = self.garble(text)
                        row["warmup"] = "garbled" if reason else "PASS"
                        if reason:
                            row["garble_reason"] = str(reason)
                        else:
                            row["characters"] = len(text)
                            row["status"] = "WARN" if row["memory_loaded"]["status"] in {"WARN", "UNKNOWN"} else "PASS"
            except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.TimeoutExpired,
                    http.client.HTTPException) as error:
                row["detail"] = type(error).__name__  # never include server output or credentials
            finally:
                if server is not None:
                    try:
                        server.stop(quiet=True)
                    except (OSError, subprocess.TimeoutExpired):
                        row["status"], row["cleanup"] = "FAIL", "stop_failed"
        failed = any(item["status"] == "FAIL" for item in [*checks, *rows])
        warned = any(item["status"] in {"WARN", "UNKNOWN"} for item in [*checks, *rows])
        receipt["status"] = "FAIL" if failed else "WARN" if warned else "PASS"
        receipt["exit_code"] = int(failed)
        return receipt

# Explicit local configuration only: no discovery, downloads or device commands.


def configured_models(model_paths=(), models_file: Path | None = None) -> list[Model]:
    import gpu_link_pins as pins
    catalog = {row['file'].casefold(): row for row in (*pins.MODELS, *pins.RX580_MODELS)}
    records = []
    if models_file is not None:
        records = json.loads(Path(models_file).read_text('utf-8'))
        if not isinstance(records, list):
            raise ValueError('Models configuration must be a list')
    entries = [(row, Path(models_file).absolute().parent) for row in records]
    entries.extend(({'path': str(path)}, Path.cwd()) for path in model_paths)
    models, seen = [], set()
    for row, base in entries:
        if not isinstance(row, dict) or not isinstance(row.get('path'), str) or not row['path']:
            raise ValueError('Each model must have a local path')
        path = Path(row['path']).expanduser()
        path = path if path.is_absolute() else base / path
        identity = path.resolve()
        if identity in seen:
            raise ValueError('Duplicate model path')
        seen.add(identity)
        pin = catalog.get(path.name.casefold())
        if pin and any(key in row and row[key] != pin[key] for key in ('size', 'sha256')):
            raise ValueError('Configured values cannot override a pinned size or SHA-256')
        try:
            actual_size = path.stat().st_size
        except OSError:
            actual_size = 1  # Missing files remain representable and fail preflight.
        size = pin['size'] if pin else row.get('size', max(1, actual_size))
        digest = pin['sha256'] if pin else row.get('sha256')
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', digest)):
            raise ValueError('Invalid SHA-256 pin')
        known_good = bool(pin) or row.get('known_good', False)
        if not isinstance(known_good, bool):
            raise ValueError('known_good must be boolean')
        family = row.get('family', '')
        if not isinstance(family, str):
            raise ValueError('family must be a string')
        models.append(Model(row.get('name', pin['label'] if pin else path.stem), size, path,
                            family=family, sha256=digest, known_good=known_good, available=False))
    return models


def _verify_watch_model(model: Model):
    if model.path is None or not model.path.is_file() or model.path.stat().st_size != model.size:
        raise ValueError('Model file is missing or has the wrong size')
    if model.sha256:
        digest = hashlib.sha256()
        with model.path.open('rb') as source:
            for block in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest().lower() != model.sha256.lower():
            raise ValueError('Model SHA-256 does not match')


def run_watch(args, models: list[Model], *, watchdog_factory=None, clock=time.monotonic,
              sleep=time.sleep, setup_module=None) -> dict:
    receipt = {'mode': 'watch', 'status': 'DISABLED', 'exit_code': 0,
               'offline': args.offline, 'downloads': 'disabled', 'events': [],
               'model_readiness': 'NOT_VERIFIED (supervision only)'}
    if not watchdog_enabled():
        return receipt
    if not safe_port(args.port) or not models or args.port + len(models) - 1 > 38499:
        raise ValueError('Configure models within the D port range')
    if args.binary is None or not args.binary.is_file():
        raise ValueError('An existing local llama-server binary is required')
    for model in models:
        _verify_watch_model(model)
    if setup_module is None:
        import gpu_link_autosetup as setup_module
    args.log_dir.mkdir(parents=True, exist_ok=True)
    events = collections.deque(maxlen=1000)
    watchdog = (watchdog_factory or Watchdog)(notify=events.append, startup_grace=args.timeout)
    try:
        # Keep keys and log handles alive for exact-command restarts, then stop
        # all our children before removing private credentials or closing logs.
        with ExitStack() as stack:
            private = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='watch-key-', dir=args.log_dir)))
            key_file = setup_module.write_key_file(secrets.token_urlsafe(32), private)
            env = setup_module.moltenvk_env(setup_module.runtime_env(args.binary), binary=args.binary)
            try:
                for index, model in enumerate(models):
                    port = args.port + index
                    command = setup_module.server_command(args.binary, model.path, port, key_file,
                                                          f'opos-health-{index + 1}', args.backend,
                                                          profile=getattr(args, 'profile', None),
                                                          device=getattr(args, 'device', None))
                    log = stack.enter_context((args.log_dir / f'health-watch-{port}.log').open('ab'))
                    options = {'stdout': log, 'stderr': subprocess.STDOUT, 'env': env}
                    if os.name == 'nt':
                        options['creationflags'] = 0x08000000
                    else:
                        options['start_new_session'] = True
                    watchdog.spawn(command, port, **options)
                start = clock()
                while args.duration is None or clock() - start < args.duration:
                    watchdog.tick()
                    if any(server.gave_up for server in watchdog.servers):
                        receipt['status'], receipt['exit_code'] = 'FAIL', 1
                        break
                    remaining = args.interval if args.duration is None else min(args.interval, args.duration - (clock() - start))
                    if remaining > 0:
                        sleep(remaining)
                else:
                    receipt['status'] = 'STOPPED'
            except KeyboardInterrupt:
                receipt['status'] = 'STOPPED'
            finally:
                watchdog.close()
                receipt['owned_servers_exited'] = all(server.process.poll() is not None for server in watchdog.servers)
    finally:
        receipt['events'] = list(events)
    return receipt


def _health_table(receipt: dict) -> str:
    rows = [('CHECK', 'STATUS', 'DETAIL')]
    for row in receipt.get('checks', []):
        detail = row.get('detail', row.get('source', ''))
        if row.get('free_percent') is not None:
            detail += f"; {row['free_percent']}% free"
        rows.append((row['check'], row['status'], detail))
    rows.extend((row['model'], row['status'], f"file={row['file']} load={row['load']} warmup={row['warmup']}")
                for row in receipt.get('models', []))
    if len(rows) == 1:
        rows.append((receipt.get('mode', 'health'), receipt['status'], receipt.get('model_readiness', '')))
    return '\n'.join(f'{check:<30} {status:<10} {detail}' for check, status, detail in rows)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Read-only local model checks and owned-server supervision')
    parser.add_argument('mode', choices=('preflight', 'watch'))
    parser.add_argument('--model-path', type=Path, action='append', default=[])
    parser.add_argument('--models-file', type=Path, help='JSON list of local path/name/size/sha256 entries')
    parser.add_argument('--binary', type=Path, help='Existing local llama-server; never downloaded')
    parser.add_argument('--backend', choices=('cpu', 'metal', 'cuda', 'vulkan', 'rocm'), default='cpu')
    parser.add_argument('--profile', help='Existing autosetup GPU quirk profile')
    parser.add_argument('--device', help='Explicit runtime device, for example Vulkan0')
    parser.add_argument('--port', type=int, default=38400)
    parser.add_argument('--timeout', type=float, default=60)
    parser.add_argument('--duration', type=float)
    parser.add_argument('--interval', type=float, default=1)
    parser.add_argument('--log-dir', type=Path, default=Path('health-logs'))
    parser.add_argument('--receipt', type=Path, default=Path('health-receipt.json'))
    parser.add_argument('--offline', action='store_true', default=os.environ.get('OPOS_GPU_LINK_OFFLINE', '').strip().lower() in {'1', 'true', 'yes', 'on'})
    args = parser.parse_args(argv)
    if not safe_port(args.port):
        parser.error('port must be in 38400-38499')
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error('timeout must be positive and finite')
    if args.duration is not None and (not math.isfinite(args.duration) or args.duration <= 0):
        parser.error('duration must be positive and finite')
    if not math.isfinite(args.interval) or args.interval < 0.1:
        parser.error('interval must be finite and at least 0.1 seconds')
    try:
        models = configured_models(args.model_path, args.models_file)
        if args.mode == 'preflight':
            receipt = Preflight(models, args.binary, args.log_dir, args.backend, args.offline,
                                args.timeout, args.port, profile=args.profile, device=args.device).run()
            receipt['mode'] = 'preflight'
        else:
            receipt = run_watch(args, models)
    except (OSError, ValueError, TypeError, KeyError, subprocess.SubprocessError) as error:
        receipt = {'mode': args.mode, 'status': 'FAIL', 'exit_code': 1,
                   'error': type(error).__name__}  # No raw messages, prompts or credentials.
    try:
        args.receipt.parent.mkdir(parents=True, exist_ok=True)
        args.receipt.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    except OSError:
        receipt = dict(receipt, status='FAIL', exit_code=1, receipt='write_failed')
    print(_health_table(receipt))
    print(json.dumps(receipt, indent=2))
    return receipt['exit_code']


if __name__ == '__main__':
    raise SystemExit(main())

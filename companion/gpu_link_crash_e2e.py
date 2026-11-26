# SPDX-License-Identifier: Apache-2.0
"""Real llama-server crash recovery inside the launcher (own server only).

Part A (in-process, same Runtime + watchdog supervisor thread the launcher starts): start our own llama-server with
--strict-ports, stream a long answer through the companion's LazyServerSource, SIGKILL our own server mid-answer,
and check that (1) the stream fails visibly, (2) the watchdog restarts the same slot on the same port, (3) the
restarted server answers a resumed request that starts with the saved partial text, (4) nothing else changed.
Part B (subprocess): run the real launcher `gpu_link_autosetup.py --no-phone --own-server --strict-ports`, SIGKILL only
its direct llama-server child, and check that the launcher itself restarts it on the same port.
Only PIDs this script's own runtime/launcher spawned are ever signalled; protected ports and PIDs are refused.
Usage: python3 gpu_link_crash_e2e.py --model-path GGUF --port 38600 --receipt out.json [--runtime-dir D]
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

import gpu_link_autosetup as a

HERE = Path(__file__).resolve().parent
PROTECTED_PORTS = {1234, 1235, 1236, 1237, 8765, 8767, 11434, 41484, 56795, 56740, 24001}
QUESTION = "Explain how a GPU renders a frame, step by step."


def listeners() -> list[str]:
    out = subprocess.run(["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         text=True, timeout=10, check=False).stdout
    return sorted(" ".join(line.split()[:2] + line.split()[8:9]) for line in out.splitlines()[1:])


def health(port: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as r:
            return r.status == 200
    except OSError:
        return False


def children_of(pid: int) -> list[int]:
    out = subprocess.run(["pgrep", "-P", str(pid)], stdout=subprocess.PIPE, text=True, check=False).stdout
    return [int(x) for x in out.split()]


def cmdline(pid: int) -> str:
    return subprocess.run(["ps", "-o", "command=", "-p", str(pid)], stdout=subprocess.PIPE, text=True,
                          check=False).stdout


def part_a(args) -> dict:
    import opos_gpu_link as link
    args.own_server = args.strict_ports = args.no_phone = True
    out: dict = {"part": "A in-process Runtime + watchdog"}
    info = a.plan(args)
    rt = a.start_runtime(args, info)
    server = rt.servers[0]
    port, pid = server.port, server.process.pid
    out.update({"port": port, "pid_before": pid, "watchdog_enabled": rt.watchdog is not None})
    assert port not in PROTECTED_PORTS and rt.watchdog is not None
    events: list[dict] = []
    rt.listen(events.append)
    try:
        lane = rt.lanes[0]
        checked, lock = set(), threading.Lock()
        src = link.LazyServerSource({"question": QUESTION, "partial": ""}, lane["url"], lane["id"], checked, lock)
        t0, data, failed = time.monotonic(), b"", False
        killed_at = None
        while time.monotonic() - t0 < 120:
            snap = src.snapshot()
            data, done, failed = snap[0], snap[1], snap[-1]
            if killed_at is None and len(data) >= 300:
                assert pid == rt.servers[0].process.pid and f"--port {port}" in " ".join(server.process.args)
                os.kill(pid, signal.SIGKILL)  # our own server only
                killed_at = time.monotonic()
            if killed_at and (failed or done):
                break
            time.sleep(0.05)
        out["killed_mid_answer"] = killed_at is not None
        out["stream_failed_visibly"] = bool(failed)
        out["partial_bytes_at_failure"] = len(data)
        partial = data.decode("utf-8", "replace")
        src.close()
        # Wait for the watchdog (1 s tick, backoff) to bring the same slot back.
        up_at = None
        for _ in range(480):
            new = rt.servers[0].process
            if new.pid != pid and health(port):
                up_at = time.monotonic()
                break
            time.sleep(0.5)
        out["restarted_same_port"] = up_at is not None
        out["restart_seconds"] = round(up_at - killed_at, 1) if up_at and killed_at else None
        out["pid_after"] = rt.servers[0].process.pid
        out["watchdog_events"] = [e.get("status") for e in events]
        if up_at:
            checked2, lock2 = set(), threading.Lock()
            src2 = link.LazyServerSource({"question": QUESTION, "partial": partial}, lane["url"], lane["id"], checked2, lock2)
            t1, data2, done2 = time.monotonic(), b"", False
            while time.monotonic() - t1 < 180:
                snap = src2.snapshot()
                data2, done2 = snap[0], snap[1]
                if done2 or snap[-1]:
                    break
                time.sleep(0.1)
            src2.close()
            text2 = data2.decode("utf-8", "replace")
            out["resumed_finished"] = bool(done2)
            out["resumed_starts_with_partial"] = text2.startswith(partial)
            out["resumed_words"] = len(text2.split())
            try:
                import gpu_link_guard as g
                out["resumed_garble_reason"] = g.garble_reason(text2, final=True)
            except ImportError:
                out["resumed_garble_reason"] = "guard-missing"
    finally:
        rt.stop()
        time.sleep(2)
    out["servers_exited"] = all(s.process.poll() is not None for s in rt.servers)
    out["pass"] = bool(out.get("killed_mid_answer") and out.get("stream_failed_visibly") and out.get("restarted_same_port")
                       and out.get("resumed_finished") and out.get("resumed_starts_with_partial")
                       and out.get("resumed_garble_reason") is None and out["servers_exited"])
    return out


def part_b(args) -> dict:
    out: dict = {"part": "B real launcher subprocess"}
    data = Path(tempfile.mkdtemp(prefix="gl-crash-b-"))
    cmd = [sys.executable, "-B", str(HERE / "gpu_link_autosetup.py"), "--no-phone", "--own-server", "--strict-ports",
           "--offline", "--no-extras", "--no-pause", "--port", str(args.port + 20), "--budget-mb", "1500",
           "--model-path", args.model_path, "--data-dir", str(data)]
    if args.runtime_dir:
        cmd += ["--runtime-dir", str(args.runtime_dir)]
    log = data / "launcher.log"
    proc = subprocess.Popen(cmd, stdout=open(log, "wb"), stderr=subprocess.STDOUT, cwd=HERE, start_new_session=True)
    try:
        kid = None
        for _ in range(480):
            kids = [k for k in children_of(proc.pid) if "llama-server" in cmdline(k)]
            ready = "Model server(s) ready" in log.read_text("utf-8", "replace")  # setup finished, supervisor running
            if kids and ready:
                kid = kids[0]
                words = cmdline(kid).split()
                port = int(words[words.index("--port") + 1])
                if health(port):
                    break
            time.sleep(0.5)
        out["launcher_pid"], out["server_pid_before"] = proc.pid, kid
        if kid is None:
            out.update({"error": "launcher never started a server", "pass": False})
            return out
        out["port"] = port
        assert port not in PROTECTED_PORTS
        os.kill(kid, signal.SIGKILL)
        t0, new = time.monotonic(), None
        for _ in range(480):
            kids = [k for k in children_of(proc.pid) if "llama-server" in cmdline(k) and k != kid]
            if kids and health(port):
                new = kids[0]
                break
            time.sleep(0.5)
        out["server_pid_after"] = new
        out["restart_seconds"] = round(time.monotonic() - t0, 1) if new else None
        out["restarted_same_port"] = bool(new)
        out["launcher_still_running"] = proc.poll() is None
        out["pass"] = bool(new and proc.poll() is None)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGTERM)  # the launcher's own process group only
            proc.wait(20)
        except (OSError, subprocess.TimeoutExpired):
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass
    time.sleep(1)
    out["log_tail"] = log.read_text("utf-8", "replace")[-600:].replace(os.path.expanduser("~"), "~")
    return out


def main(argv=None) -> int:
    args = a.arguments(argv)
    receipt = {"started": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "listeners_before": listeners()}
    receipt["A"] = part_a(args)
    time.sleep(2)
    receipt["B"] = part_b(args)
    time.sleep(2)
    receipt["listeners_after"] = listeners()
    receipt["listeners_unchanged"] = receipt["listeners_before"] == receipt["listeners_after"]
    receipt["pass"] = bool(receipt["A"].get("pass") and receipt["B"].get("pass") and receipt["listeners_unchanged"])
    path = args.receipt or Path("crash-e2e.json")
    Path(path).write_text(json.dumps(receipt, indent=2, default=str))
    print(json.dumps({k: v for k, v in receipt.items() if k not in ("listeners_before", "listeners_after")}, indent=2, default=str))
    return 0 if receipt["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

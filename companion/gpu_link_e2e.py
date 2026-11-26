# SPDX-License-Identifier: Apache-2.0
"""Headless end-to-end check, with NO phone: `opos-gpu-link --e2e`.

Brings up exactly what a real run would (runtime, models, servers), then:
 - proves the security settings (key required, CORS refused, loopback-only,
   key absent from logs/argv/disk),
 - runs every PC lane through the companion's own preflight and stream code
   (LazyServerSource, the class a phone lane uses), concurrently,
 - simulates a cable pull mid-answer and a replug that resumes from the saved
   partial text,
 - checks the companion accepts the generated lane arguments,
 - stops everything and checks GPU memory is released.
It writes a JSON receipt. It never prints the key or other processes' arguments.
"""
from __future__ import annotations

import http.client
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import gpu_link_autosetup as a

try:
    from gpu_link_guard import garble_reason
except ImportError:
    garble_reason = None  # Optional until older companion copies are integrated.

QUESTION = "Explain how a GPU renders a frame, step by step."


def gpu_used_mb(gpu=None):
    """Dedicated VRAM in use on the GPU the launcher chose (nvidia-smi for NVIDIA; Windows GPU counters or
    amdgpu sysfs for AMD/Intel Vulkan). None when it cannot be measured on this OS."""
    if gpu is not None:
        return a.vram_used_mb(gpu)
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=10)
        return int(out.stdout.decode().split()[0])
    except (OSError, IndexError, ValueError, subprocess.TimeoutExpired):
        return None


def http_status(port, headers=None, path="/v1/models"):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("GET", path, headers=headers or {})
        response = conn.getresponse()
        response.read()
        return response.status, {k.lower(): v for k, v in response.getheaders()}
    except OSError as error:
        return type(error).__name__, {}
    finally:
        conn.close()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("203.0.113.1", 9))  # TEST-NET: routing lookup only, nothing is sent
        ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None
    finally:
        s.close()


def server_args_contain(pid, needle):
    try:
        if Path(f"/proc/{pid}/cmdline").exists():
            return needle.encode() in Path(f"/proc/{pid}/cmdline").read_bytes()
        out = subprocess.run(["ps", "-p", str(pid), "-o", "args="], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, check=False, timeout=5).stdout.decode()
        return needle in out
    except (OSError, subprocess.TimeoutExpired):
        return None


def security_checks(rt):
    lead = rt.servers[0]
    port = lead.port
    out = {}
    out["no_key_status"] = http_status(port)[0]
    out["wrong_key_status"] = http_status(port, {"Authorization": "Bearer not-the-key"})[0]
    status, hdrs = http_status(port, {"Authorization": "Bearer " + rt.key, "Origin": "http://evil.example"})
    out["evil_origin_status"] = status
    out["evil_origin_allowed"] = "access-control-allow-origin" in hdrs
    out["right_key_status"] = http_status(port, {"Authorization": "Bearer " + rt.key})[0]
    ip = lan_ip()
    out["lan_ip_tested"] = bool(ip)
    if ip:
        try:
            socket.create_connection((ip, port), timeout=2).close()
            out["reachable_on_lan_ip"] = True
        except OSError:
            out["reachable_on_lan_ip"] = False
    logs = [s.log_path.read_text("utf-8", "replace") for s in rt.servers]
    out["key_in_logs"] = any(rt.key in text for text in logs)
    out["key_in_server_argv"] = any(server_args_contain(s.process.pid, rt.key) for s in rt.servers)
    out["key_file_removed"] = rt.key_file is None
    try:
        envs = [Path(f"/proc/{s.process.pid}/environ").read_bytes() for s in rt.servers]
        out["key_in_server_environment"] = any(rt.key.encode() in e for e in envs)
    except OSError:
        out["key_in_server_environment"] = None  # not readable on this OS
    out["our_servers_listed_as_open_backends"] = [
        b["url"] for b in a.find_existing_servers(strict_ports=True)
        if any(b["url"].endswith(f":{s.port}") for s in rt.servers)]
    out["pass"] = (out["no_key_status"] == 401 and out["wrong_key_status"] == 401
                   and not out["evil_origin_allowed"]  # no Access-Control-Allow-Origin for a foreign page
                   and out["right_key_status"] == 200 and out.get("reachable_on_lan_ip") is not True
                   and not out["key_in_logs"] and out["key_in_server_argv"] is not True
                   and out["key_in_server_environment"] is not True
                   and out["key_file_removed"] and not out["our_servers_listed_as_open_backends"])
    return out


def degenerate_text(text: str) -> str | None:
    """Why a finished answer is garbage (a run like "@@@@..." or a looped fragment), else None.

    Found on the Mac Pro RX 580: both lanes answered the first ~540 tokens correctly, then printed "@@@@" / "8888" /
    "asks8alion" until the length limit, and the e2e still passed because it only checked that words arrived.
    """
    reason = garble_reason(text, final=True) if garble_reason is not None else None
    return {"repeat_char": "long run of one repeated character",
            "ngram_loop": "answer ends in a repeating loop"}.get(reason, reason)


def stream(link, lane, partial, stop_after_bytes=None, timeout=180):
    checked, lock = set(), threading.Lock()
    source = link.LazyServerSource({"question": QUESTION, "partial": partial}, lane["url"], lane["id"], checked, lock)
    start = time.monotonic()
    first, data, done = None, b"", False
    while time.monotonic() - start < timeout:
        data, done = source.snapshot()[:2]
        if data and first is None:
            first = time.monotonic() - start
        if done or (stop_after_bytes and len(data) >= stop_after_bytes):
            break
        time.sleep(0.01)
    elapsed = time.monotonic() - start
    source.close()
    return {"data": data, "done": done, "first": first, "elapsed": elapsed}


def parallel(fn, lanes):
    results = [None] * len(lanes)

    def work(i, lane):
        results[i] = fn(lane)
    threads = [threading.Thread(target=work, args=(i, l)) for i, l in enumerate(lanes)]
    t0 = time.monotonic()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results, time.monotonic() - t0


def run(args) -> int:
    import opos_gpu_link as link
    args.own_server = True
    args.strict_ports = True
    args.no_phone = True
    receipt = {"started": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "frozen": a.FROZEN,
               "phone": "NOT ATTACHED (headless fake-phone lanes)", "python": sys.version.split()[0]}
    out_path = args.receipt or (args.data_dir / "receipts" / "e2e.json")
    t0 = time.monotonic()
    info = a.plan(args)
    vram_before = gpu_used_mb(info["gpu"])
    receipt["gpu_hidden_nvidia"] = a.hide_nvidia()
    receipt["backend"] = info["gpu"]["backend"]
    receipt["detect"] = {"gpu": info["gpu"], "model": info["model"], "extras": info["extras"],
                         "runtime": info["runtime"]}
    try:
        rt = a.start_runtime(args, info)
    except RuntimeError as error:
        receipt["backend"] = info["gpu"]["backend"]
        receipt.update({"pass": False, "failed_at": "start_runtime", "error": str(error)[:600]})
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(receipt, indent=2, default=str))
        print(json.dumps(receipt, indent=2, default=str))
        return 2
    receipt["backend"] = info["gpu"]["backend"]
    receipt["setup_seconds"] = round(time.monotonic() - t0, 1)
    receipt["lanes"] = [{k: v for k, v in lane.items() if k != "url"} | {"url_port": lane.get("port")}
                        for lane in rt.lanes]
    receipt["vulkan_device"] = getattr(rt, "device", None)
    receipt["lead_on_gpu"] = rt.on_gpu
    receipt["lead_evidence"] = rt.evidence
    receipt["all_lanes_on_gpu"] = all(l.get("on_gpu") for l in rt.lanes)
    ok = info["gpu"]["backend"] == "cpu" or bool(rt.on_gpu)
    try:
        time.sleep(2)
        receipt["vram_mb"] = {"before": vram_before, "loaded": gpu_used_mb(info["gpu"])}
        receipt["security"] = security_checks(rt)
        ok &= receipt["security"]["pass"]
        cancelled = threading.Event()
        pre = []
        for lane in rt.lanes:
            t = time.monotonic()
            res = link.model_server_preflight(lane["url"], lane["id"], cancelled.is_set)
            pre.append({"lane": lane["id"], "ok": bool(res), "seconds": round(time.monotonic() - t, 2)})
        receipt["preflight"] = pre
        ok &= all(p["ok"] for p in pre)
        full, wall = parallel(lambda l: stream(link, l, ""), rt.lanes)
        receipt["answers_concurrent"] = {
            "wall_seconds": round(wall, 2),
            "lanes": [{"lane": l["id"], "words": len(r["data"].decode("utf-8", "replace").split()),
                       "finished": r["done"], "first_text_s": round(r["first"] or -1, 3),
                       "seconds": round(r["elapsed"], 2),
                       "words_per_s": round(len(r["data"].decode("utf-8", "replace").split()) / max(r["elapsed"], 0.01), 1),
                       "degenerate": degenerate_text(r["data"].decode("utf-8", "replace"))}
                      for l, r in zip(rt.lanes, full)]}
        ok &= all(r["done"] and r["data"] for r in full)
        ok &= not any(l["degenerate"] for l in receipt["answers_concurrent"]["lanes"])
        cut, _ = parallel(lambda l: stream(link, l, "", stop_after_bytes=400), rt.lanes)
        resumed, _ = parallel(lambda l: stream(link, l, next(c for c, ln in zip(cut, rt.lanes) if ln is l)["data"].decode("utf-8", "replace")), rt.lanes)
        replug = []
        for lane, c, r in zip(rt.lanes, cut, resumed):
            replug.append({"lane": lane["id"], "partial_bytes": len(c["data"]), "resumed_bytes": len(r["data"]),
                           "resume_finished": r["done"], "resume_starts_with_partial": r["data"].startswith(c["data"])})
        receipt["unplug_replug"] = replug
        ok &= all(x["resume_finished"] and x["resume_starts_with_partial"] for x in replug)
        parsed = link.arguments(a.companion_args(args, rt, info, Path("adb"), "FAKE123"))
        receipt["companion_args_accepted"] = {"extra_models": [m["id"] for m in parsed.extra_models],
                                              "model_servers": sorted(parsed.model_servers)}
        ok &= sorted(parsed.model_servers) == sorted(m["id"] for m in parsed.extra_models)
        speeds = []
        for server in rt.servers:
            text = server.log_path.read_text("utf-8", "replace")
            speeds.append({"alias": server.alias, "tokens_per_second": [float(x) for x in re.findall(
                r"eval time =.*?([\d.]+) tokens per second", text)][-2:],
                "offload": a.parse_offload_log(text)})
        receipt["servers"] = speeds
    finally:
        rt.stop()
        os.environ.pop(a.KEY_ENV, None)
        time.sleep(3)
        receipt.setdefault("vram_mb", {})["after_stop"] = gpu_used_mb(info["gpu"])
        receipt["vram_mb"]["gpu"] = info["gpu"].get("name")
        receipt["servers_exited"] = all(s.process.poll() is not None for s in rt.servers)
    receipt["vram_measured"] = vram_before is not None and receipt["vram_mb"]["after_stop"] is not None
    tolerance = 300 if info["gpu"].get("integrated") else 50  # an iGPU's shared memory moves with the desktop
    receipt["vram_released"] = (not receipt["vram_measured"]
                                or receipt["vram_mb"]["after_stop"] <= vram_before + tolerance)
    receipt["pass"] = bool(ok and receipt["servers_exited"] and receipt["vram_released"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, indent=2, default=str))
    print(json.dumps(receipt, indent=2, default=str))
    return 0 if receipt["pass"] else 1

# SPDX-License-Identifier: Apache-2.0
"""Headless end-to-end check on a real computer, with no phone attached.

1. Plug-and-play detection + runtime/model setup (downloads only if missing).
2. Launch our own llama-server on a free port (default 18090), verify GPU use.
3. The companion's own one-token preflight against that server.
4. A fake phone lane (the companion's LazyServerSource, exactly what a PC lane
   uses) streams a real answer, is "unplugged" mid-answer, then resumed from
   its acknowledged partial text, like a cable replug.
5. Re-detection finds our running server as an existing backend.
6. Stop the server (unload) and confirm GPU memory is released.
Writes a JSON receipt. Never prints keys or other processes' command lines.
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gpu_link_autosetup as a  # noqa: E402
import opos_gpu_link as link  # noqa: E402

QUESTION = "Explain how a GPU renders a frame, step by step."


def gpu_used_mb():
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False).stdout.decode()
    try:
        return int(out.split()[0])
    except (IndexError, ValueError):
        return None


def stream(url, model, partial, stop_after_bytes=None, timeout=120):
    checked, lock = set(), threading.Lock()
    source = link.LazyServerSource({"question": QUESTION, "partial": partial}, url, model, checked, lock)
    start = time.monotonic()
    first = None
    data, done = b"", False
    while time.monotonic() - start < timeout:
        data, done = source.snapshot()[:2]
        if data and first is None:
            first = time.monotonic() - start
        if done or (stop_after_bytes and len(data) >= stop_after_bytes):
            break
        time.sleep(0.01)
    elapsed = time.monotonic() - start
    source.close()
    return data, done, first, elapsed


def main():
    receipt = {"started": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "phone": "NOT ATTACHED (headless fake-phone lane)"}
    args = a.arguments(["--strict-ports", "--own-server", "--no-phone"] + sys.argv[1:])
    vram_before = gpu_used_mb()
    t0 = time.monotonic()
    info = a.plan(args)
    receipt["detect"] = {"gpu": info["gpu"], "runtime": info["runtime"], "model": info["model"]}
    url, model, server, on_gpu, evidence = a.start_runtime(args, info)
    receipt["setup_seconds"] = round(time.monotonic() - t0, 1)
    receipt["server"] = {"url": url, "port": server.port, "on_gpu": on_gpu, "evidence": evidence,
                         "log": str(server.log_path)}
    try:
        time.sleep(2)
        receipt["vram_mb"] = {"before": vram_before, "loaded": gpu_used_mb()}
        cancelled = threading.Event()
        t = time.monotonic()
        ok = link.model_server_preflight(url, model, cancelled.is_set)
        receipt["preflight"] = {"ok": bool(ok), "seconds": round(time.monotonic() - t, 2)}
        # Full answer, uninterrupted.
        data, done, first, elapsed = stream(url, model, "")
        words = len(data.decode("utf-8", "replace").split())
        receipt["full_answer"] = {"bytes": len(data), "words": words, "finished": done,
                                  "first_text_s": round(first or -1, 3), "seconds": round(elapsed, 2)}
        # Unplug mid-answer, then replug and resume from the acknowledged partial.
        part, done1, _, _ = stream(url, model, "", stop_after_bytes=400)
        partial = part.decode("utf-8", "replace")
        resumed, done2, first2, elapsed2 = stream(url, model, partial)
        receipt["unplug_replug"] = {"partial_bytes": len(part), "finished_before_unplug": done1,
                                    "resumed_bytes": len(resumed), "resume_finished": done2,
                                    "resume_starts_with_partial": resumed.startswith(part),
                                    "resume_first_text_s": round(first2 or -1, 3),
                                    "resume_seconds": round(elapsed2, 2)}
        # Our server should now be auto-detected as an existing backend.
        found = a.find_existing_servers(strict_ports=True)
        receipt["redetect"] = [{"url": b["url"], "kind": b["kind"], "models": b["models"]} for b in found]
        # Speed from the server's own timing lines.
        text = server.log_path.read_text("utf-8", "replace")
        speeds = [float(x) for x in __import__("re").findall(r"eval time =.*?([\d.]+) tokens per second", text)
                  if x]
        receipt["server_tokens_per_second"] = speeds[-3:]
        receipt["offload"] = a.parse_offload_log(text)
    finally:
        server.stop()
        time.sleep(3)
        receipt["vram_mb"] = {**receipt.get("vram_mb", {}), "after_stop": gpu_used_mb()}
        receipt["server_exited"] = server.process.poll() is not None
    out = HERE.parent / "receipts" / "e2e-5080.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(receipt, indent=2, default=str))
    print(json.dumps(receipt, indent=2, default=str))


if __name__ == "__main__":
    main()

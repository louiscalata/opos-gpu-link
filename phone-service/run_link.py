#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the phone side of OPOS GPU Link on its own.

Starts the loopback listener that the PC companion reaches through the USB
forward (adb forward tcp:<pc port> tcp:8767), with answers and pairing kept
under the state directory. Ctrl-C or SIGTERM stops it cleanly.

  python3 -B run_link.py [--port 8767] [--label "My phone"] [--model FILE.gguf] [--state-dir DIR]
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from opos import ai_answers, gpu_link_proto, gpu_link_server  # noqa: E402


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the OPOS GPU Link phone listener on loopback.")
    p.add_argument("--port", type=int, default=8767, help="loopback port (default 8767)")
    p.add_argument("--label", default="OPOS phone", help="name the PC shows for this phone")
    p.add_argument("--model", type=Path, help="optional model file the PC may copy")
    p.add_argument("--state-dir", type=Path,
                   help="where pairing and answers are kept (default $XDG_STATE_HOME or ~/.local/state)")
    args = p.parse_args(argv)
    if not 0 <= args.port <= 65535:
        p.error("--port must be 0-65535")
    if not gpu_link_proto.valid_label(args.label):
        p.error("--label is not a valid link label")
    if args.model is not None and not args.model.is_file():
        p.error(f"--model {args.model} is not a file")
    return args


def environment(args: argparse.Namespace) -> dict[str, str]:
    env = {"OPOS_GPU_LINK": "1", "OPOS_GPU_LINK_PORT": str(args.port), "OPOS_GPU_LINK_LABEL": args.label}
    if args.model is not None:
        env["OPOS_GPU_LINK_MODEL"] = str(args.model)
    if args.state_dir is not None:
        env["XDG_STATE_HOME"] = str(args.state_dir)
    return env


def main(argv: list[str] | None = None, stop: threading.Event | None = None,
         ready: Callable[[int], None] | None = None) -> int:
    args = arguments(argv)
    env = environment(args)
    if args.state_dir is not None:
        args.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.environ["XDG_STATE_HOME"] = env["XDG_STATE_HOME"]  # the answer store reads it too
    stop = stop or threading.Event()
    if threading.current_thread() is threading.main_thread():
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, lambda *_: stop.set())
    try:
        gpu_link_server.start(ai_answers.shared(), env)
    except (OSError, ValueError, OverflowError, RuntimeError) as err:
        print(f"GPU Link could not start: {type(err).__name__}: {err}", file=sys.stderr)
        return 1
    try:
        port = gpu_link_server.listening_port()
        print(f"GPU Link phone listener on 127.0.0.1:{port} as {args.label!r}. Ctrl-C to stop.", flush=True)
        if ready is not None:
            ready(port)
        while not stop.wait(0.5):
            pass
    finally:
        gpu_link_server.stop()
        print("GPU Link phone listener stopped.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

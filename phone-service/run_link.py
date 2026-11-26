#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the phone side of OPOS GPU Link on its own.

Starts two loopback servers, with answers and pairing kept under the state directory:

- the GPU Link listener the PC companion reaches through the USB forward
  (adb forward tcp:<pc port> tcp:8767), and
- the app API on 127.0.0.1:8765 (GET /ai, GET and POST /api/ai) that the
  OPOS GPU Link Android app reads.

The phone lane is optional: --phone-url names an OpenAI-compatible server on
this phone's loopback (for example llama.cpp's llama-server) and --phone-model
the model to ask. Ctrl-C or SIGTERM stops everything cleanly.

  python3 -B run_link.py [--port 8767] [--app-port 8765 | --no-app-api] [--label "My phone"]
      [--model FILE.gguf] [--phone-url http://127.0.0.1:8080/v1 --phone-model NAME] [--state-dir DIR]
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

from opos import ai_answers, gpu_link_proto, gpu_link_server, link_api  # noqa: E402


def arguments(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the OPOS GPU Link phone listener on loopback.")
    p.add_argument("--port", type=int, default=8767, help="loopback port (default 8767)")
    p.add_argument("--label", default="OPOS phone", help="name the PC shows for this phone")
    p.add_argument("--model", type=Path, help="optional model file the PC may copy")
    p.add_argument("--state-dir", type=Path,
                   help="where pairing and answers are kept (default $XDG_STATE_HOME or ~/.local/state)")
    p.add_argument("--app-port", type=int, default=8765, help="app API loopback port (default 8765)")
    p.add_argument("--no-app-api", action="store_true", help="run only the PC-facing listener")
    p.add_argument("--phone-url", help="OpenAI-compatible server on this phone, e.g. http://127.0.0.1:8080/v1")
    p.add_argument("--phone-model", help="model name to ask on --phone-url")
    args = p.parse_args(argv)
    if not 0 <= args.port <= 65535:
        p.error("--port must be 0-65535")
    if not 0 <= args.app_port <= 65535:
        p.error("--app-port must be 0-65535")
    if bool(args.phone_url) != bool(args.phone_model):
        p.error("--phone-url and --phone-model go together")
    args.phone = None
    if args.phone_url:
        try:
            args.phone = link_api.PhoneModel(args.phone_url, args.phone_model)
        except ValueError as err:
            p.error(str(err))
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
         ready: Callable[[int], None] | None = None,
         app_ready: Callable[[link_api.AppServer], None] | None = None) -> int:
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
    app = None
    try:
        if not args.no_app_api:
            try:
                app = link_api.AppServer(link_api.LinkApi(args.phone), port=args.app_port)
            except (OSError, ValueError, OverflowError) as err:
                print(f"The app API could not start: {type(err).__name__}: {err}", file=sys.stderr)
                return 1
            app.start()
        port = gpu_link_server.listening_port()
        print(f"GPU Link phone listener on 127.0.0.1:{port} as {args.label!r}. Ctrl-C to stop.", flush=True)
        if app is not None:
            lane = f"phone lane via {args.phone.label!r}" if args.phone else "no phone lane"
            print(f"App API on http://127.0.0.1:{app.port}/api/ai ({lane}).", flush=True)
            if app_ready is not None:
                app_ready(app)
        if ready is not None:
            ready(port)
        while not stop.wait(0.5):
            pass
    finally:
        if app is not None:
            app.stop()
        gpu_link_server.stop()
        print("GPU Link phone listener stopped.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

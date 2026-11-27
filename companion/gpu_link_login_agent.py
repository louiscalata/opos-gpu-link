#!/usr/bin/env python3
"""Start the GPU Link companion when you log in to your Mac.

Writes a per-user LaunchAgent (~/Library/LaunchAgents/os.opos.gpulink.companion.plist)
that runs gpu_link_autosetup.py from this checkout, offline, on its own llama-server and
fixed ports, so the phone finds the computer as soon as you sign in and plug in the cable.
No admin rights, nothing system-wide, and no network access beyond localhost.

    python3 gpu_link_login_agent.py install [--model-path PATH] [--serial SERIAL] [--adb PATH]
    python3 gpu_link_login_agent.py status
    python3 gpu_link_login_agent.py uninstall
    python3 gpu_link_login_agent.py print       # show the plist without installing

The companion keeps asking the phone once before a new computer is used; this agent only
starts it.
"""
from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
import time
from pathlib import Path

LABEL = "os.opos.gpulink.companion"
DEFAULT_PORT = 38400
HERE = Path(__file__).resolve().parent
LAUNCHD_PATH = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"


def agent_path(home: Path | None = None) -> Path:
    return (home or Path.home()) / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def companion_args(python: str, companion_dir: Path, *, port: int = DEFAULT_PORT,
                   model_path: str | None = None, serial: str | None = None,
                   adb: str | None = None, log_dir: str | None = None) -> list[str]:
    """The companion command line: offline, strict ports, own server, no prompts."""
    args = [python, "-u", "-B", str(companion_dir / "gpu_link_autosetup.py"),
            "--offline", "--strict-ports", "--own-server", "--port", str(port),
            "--no-extras", "--no-pause"]
    if serial:
        args += ["--serial", serial]
    if adb:
        args += ["--adb", adb]
    if model_path:
        args += ["--model-path", model_path]
    if log_dir:
        args += ["--log-dir", log_dir]
    return args


def build_plist(args: list[str], companion_dir: Path, log_dir: Path) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": list(args),
        "WorkingDirectory": str(companion_dir),
        "RunAtLoad": True,
        # Restart after a crash, not after a clean exit (for example when you quit it).
        "KeepAlive": {"SuccessfulExit": False},
        "ThrottleInterval": 15,
        # Time to stop the model server(s) cleanly after SIGTERM before launchd kills the job.
        "ExitTimeOut": 30,
        "ProcessType": "Interactive",
        # Owned llama-servers stay in this job's process group, so launchd stops them with the
        # job even after a crash (see gpu_link_autosetup.server_session_options).
        "EnvironmentVariables": {"PATH": LAUNCHD_PATH, "PYTHONUNBUFFERED": "1",
                                 "OPOS_GPU_LINK_JOB_GROUP": "1"},
        "StandardOutPath": str(log_dir / "companion.out.log"),
        "StandardErrorPath": str(log_dir / "companion.err.log"),
    }


def _launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def absolute(path: str | None) -> str | None:
    """launchd does not expand ~ and the job runs from companion/, so store absolute paths."""
    return os.path.abspath(os.path.expanduser(path)) if path else path


def executable(path: str | None, which=shutil.which) -> str | None:
    """A program path for launchd: a bare name such as "adb" or "python3" is looked up on PATH
    (keeping a venv python's symlink); anything else becomes absolute. Raises if not found."""
    if not path:
        return path
    if os.sep not in path and not path.startswith("~"):
        found = which(path)
        if not found:
            raise SystemExit(f"{path}: not found on PATH; pass the full path")
        return found
    return absolute(path)


def wait_unloaded(loaded=None, sleep=time.sleep, timeout_s: float = 40.0) -> bool:
    """bootout returns before the old job (and its model server) has stopped; wait for it."""
    loaded = loaded or (lambda: _launchctl("print", f"{_domain()}/{LABEL}").returncode == 0)
    waited = 0.0
    while loaded():
        if waited >= timeout_s:
            return False
        sleep(0.25)
        waited += 0.25
    return True


def _domain() -> str:
    return f"gui/{os.getuid()}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("action", choices=["install", "uninstall", "status", "print"])
    p.add_argument("--python", default=sys.executable, help="Python to run the companion with")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("--model-path", help="GGUF file the companion serves")
    p.add_argument("--serial", help="phone USB serial")
    p.add_argument("--adb", help="adb executable")
    p.add_argument("--log-dir", help="companion receipts directory (passed to --log-dir)")
    p.add_argument("--no-start", action="store_true", help="install for next login only")
    a = p.parse_args(argv)

    plist_file = agent_path()
    if a.action == "status":
        r = _launchctl("print", f"{_domain()}/{LABEL}")
        print(f"{plist_file}: {'installed' if plist_file.exists() else 'not installed'}")
        print("loaded" if r.returncode == 0 else "not loaded")
        return 0
    if a.action == "uninstall":
        _launchctl("bootout", f"{_domain()}/{LABEL}")
        if not wait_unloaded():
            print("the companion agent did not stop within 40 s; nothing removed", file=sys.stderr)
            return 1
        if plist_file.exists():
            plist_file.unlink()
        print(f"removed {plist_file}")
        return 0

    agent_logs = Path.home() / "Library" / "Logs" / "OPOS GPU Link"
    args = companion_args(executable(a.python), HERE, port=a.port,
                          model_path=absolute(a.model_path), serial=a.serial,
                          adb=executable(a.adb), log_dir=absolute(a.log_dir))
    data = plistlib.dumps(build_plist(args, HERE, agent_logs))
    if a.action == "print":
        sys.stdout.write(data.decode())
        return 0

    agent_logs.mkdir(parents=True, exist_ok=True)
    plist_file.parent.mkdir(parents=True, exist_ok=True)
    _launchctl("bootout", f"{_domain()}/{LABEL}")
    if not wait_unloaded():
        print("the previous companion agent did not stop within 40 s; try again", file=sys.stderr)
        return 1
    plist_file.write_bytes(data)
    print(f"wrote {plist_file}")
    if a.no_start:
        return 0
    r = _launchctl("bootstrap", _domain(), str(plist_file))
    if r.returncode != 0:
        print(r.stderr.strip() or "launchctl bootstrap failed", file=sys.stderr)
        return 1
    print("started; it will also start at every login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

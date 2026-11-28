#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Read-only adb checklist for a hands-on GPU Link demo sitting."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from typing import Callable, Optional, Sequence


# The only argv shapes this module may send to its runner. Values substituted
# for {adb} and {serial} remain single argv elements; no shell is involved.
ALLOWED_ARGV_PATTERNS = (
    ("{adb}", "devices", "-l"),
    ("{adb}", "-s", "{serial}", "shell", "dumpsys", "thermalservice"),
    ("{adb}", "-s", "{serial}", "shell", "dumpsys", "battery"),
    ("{adb}", "-s", "{serial}", "shell", "dumpsys", "SurfaceFlinger", "--display-id"),
    ("{adb}", "-s", "{serial}", "shell", "dumpsys", "window", "policy"),
)


def allowed_argv(argv: Sequence[str], adb: str, serial: Optional[str]) -> bool:
    for pattern in ALLOWED_ARGV_PATTERNS:
        if "{serial}" in pattern and serial is None:
            continue
        expected = tuple(adb if part == "{adb}" else
                         serial if part == "{serial}" else part for part in pattern)
        if tuple(argv) == expected:
            return True
    return False


def read_adb(argv: Sequence[str], adb: str, serial: Optional[str],
             runner: Callable[..., subprocess.CompletedProcess]) -> Optional[str]:
    if not allowed_argv(argv, adb, serial):
        raise ValueError("adb command is outside the read-only allowlist")
    try:
        result = runner(list(argv), capture_output=True, encoding="utf-8",
                        errors="replace", check=False, timeout=10)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def devices(output: str) -> list[tuple[str, str, bool]]:
    found = []
    for line in output.splitlines():
        if line.startswith("List of devices attached") or line.startswith("*"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            found.append((parts[0], parts[1], any(part.startswith("usb:") for part in parts[2:])))
    return found


def usb_serial(serial: str) -> bool:
    """Exclude wireless adb and emulator transports, even if they claim USB metadata."""
    return not (re.search(r"\s", serial) or serial.startswith("emulator-") or
                "._tcp" in serial or re.search(r":\d+\Z", serial))


def flag(output: str, names: Sequence[str]) -> Optional[bool]:
    for name in names:
        match = re.search(r"\b" + re.escape(name) + r"\s*[=:]\s*(true|false)\b",
                          output, re.IGNORECASE)
        if match:
            return match.group(1).lower() == "true"
    return None


def delegate_states(output: str) -> tuple[Optional[bool], Optional[bool]]:
    """Return screen and lock state only from one complete delegate block."""
    lines = output.splitlines()
    blocks = []
    for index, line in enumerate(lines):
        if not re.search(r"\bKeyguardServiceDelegate\b", line):
            continue
        expanded = line.expandtabs()
        indent = len(expanded) - len(expanded.lstrip())
        block = []
        for child in lines[index + 1:]:
            if not child.strip():
                continue
            expanded_child = child.expandtabs()
            child_indent = len(expanded_child) - len(expanded_child.lstrip())
            if child_indent <= indent:
                break
            block.append(child)
        blocks.append("\n".join(block))
    if len(blocks) != 1:
        return None, None

    def one_value(name: str, valid_value: str) -> Optional[str]:
        found = re.findall(r"(?<!\w)" + re.escape(name) + r"[ \t]*=[ \t]*([^\s,;}]*)",
                           blocks[0], re.IGNORECASE)
        if len(found) != 1 or not re.fullmatch(valid_value, found[0], re.IGNORECASE):
            return None
        return found[0].upper()

    showing = one_value("showing", "true|false")
    screen_state = one_value("screenState", r"SCREEN_STATE_\w+")
    interactive_state = one_value("interactiveState", r"INTERACTIVE_STATE_\w+")
    screen = None if screen_state is None or interactive_state is None else (
        screen_state == "SCREEN_STATE_ON" and
        interactive_state == "INTERACTIVE_STATE_AWAKE")
    locked = showing == "TRUE" if showing is not None else None
    return screen, locked


def state_text(state: Optional[bool], legacy: Optional[bool],
               true_text: str, false_text: str) -> str:
    if state is not None:
        return true_text if state else false_text
    if legacy is not None:
        return f"unknown (legacy {true_text if legacy else false_text})"
    return "unknown"


def run_preflight(adb: str, serial: Optional[str],
                  runner: Callable[..., subprocess.CompletedProcess],
                  emit: Callable[[str], None]) -> int:
    listing = read_adb([adb, "devices", "-l"], adb, serial, runner)
    if listing is None:
        emit("FAIL device: adb devices unavailable")
        emit("Fix: check the --adb path and device connection, then rerun.")
        return 1

    found = devices(listing)
    ready = [item for item in found if item[1] == "device" and item[2] and usb_serial(item[0])]
    if serial is None:
        chosen = ready[0] if len(ready) == 1 else None
    else:
        matches = [item for item in ready if item[0] == serial]
        chosen = matches[0] if len(matches) == 1 else None
    if chosen is None:
        states = ", ".join(
            f"{name} ({state})" +
            (" (not a USB phone)" if state == "device" and not usb_serial(name) else
             " (USB connection not shown)" if state == "device" and not usb else "")
            for name, state, usb in found) or "none"
        emit(f"FAIL device: {states}")
        emit("Fix: connect and allow a USB phone; use --serial if several are ready.")
        return 1

    serial = chosen[0]
    emit(f"PASS device: {serial}")

    def dump(*parts: str) -> Optional[str]:
        return read_adb([adb, "-s", serial, "shell", "dumpsys", *parts], adb, serial, runner)

    failed = False
    thermal = dump("thermalservice")
    if thermal is None:
        emit("FAIL thermal: read unavailable")
        failed = True
    else:
        match = re.search(r"\bThermal Status:\s*(\d+)\b", thermal, re.IGNORECASE)
        if not match:
            emit("WARN thermal: status unknown")
        else:
            status = int(match.group(1))
            grade = "PASS" if status <= 2 else "WARN" if status == 3 else "FAIL"
            emit(f"{grade} thermal: status {status}")
            failed |= grade == "FAIL"

    battery = dump("battery")
    if battery is None:
        emit("WARN battery: read unavailable")
    else:
        match = re.search(r"^\s*level:\s*(\d+)\s*$", battery, re.IGNORECASE | re.MULTILINE)
        level = int(match.group(1)) if match else None
        if level is not None and not 0 <= level <= 100:
            level = None
        usb = flag(battery, ("USB powered",))
        grade = "WARN" if level is None or usb is None or level < 30 else "PASS"
        level_text = f"{level}%" if level is not None else "unknown"
        usb_text = "yes" if usb is True else "no" if usb is False else "unknown"
        emit(f"{grade} battery: {level_text}; USB powered {usb_text}")

    displays = dump("SurfaceFlinger", "--display-id")
    ids = (list(dict.fromkeys(re.findall(
        r"^\s*Display(?:\s+ID)?\s*[:=]?\s*(0x[0-9a-fA-F]+|\d+)\b",
        displays, re.IGNORECASE | re.MULTILINE))) if displays is not None else [])
    emit(f"PASS display IDs: {', '.join(ids)} (info only)" if ids else
         "WARN display IDs: none found")

    window = dump("window", "policy")
    screen, locked = delegate_states(window) if window else (None, None)
    legacy_screen = flag(window, ("mScreenOnFully", "mScreenOn", "mInteractive")) if window else None
    legacy_locked = flag(window, ("mKeyguardLocked", "mKeyguardShowing",
                                  "mShowingLockscreen")) if window else None
    screen_text = state_text(screen, legacy_screen, "on", "off")
    lock_text = state_text(locked, legacy_locked, "locked", "unlocked")
    grade = "PASS" if screen is True and locked is False else "WARN"
    emit(f"{grade} screen: {screen_text}; screen lock {lock_text}")
    return int(failed)


def main(argv: Optional[Sequence[str]] = None,
         runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
         emit: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default=os.environ.get("ADB") or "adb",
                        help="adb executable; use the same one as the companion so the adb server is not restarted (default: $ADB, else adb on PATH)")
    parser.add_argument("--serial", help="device serial when several devices are listed")
    args = parser.parse_args(argv)
    if not args.adb or args.serial == "":
        parser.error("--adb and --serial must be nonempty")
    return run_preflight(args.adb, args.serial, runner, emit)


if __name__ == "__main__":
    raise SystemExit(main())

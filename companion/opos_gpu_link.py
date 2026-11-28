# SPDX-License-Identifier: Apache-2.0
"""Connect this computer's model to an Android phone over USB-C.

This program is deliberately inert until a person starts it on their own computer.
It is not run against a phone by the build or the tests.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import http.client
import json
import os
import platform
import queue
import re
import secrets
import shutil
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path

import gpu_link_discover
from gpu_link_worker import (
    server_auth_headers,
    GuardRetryBudget,
    PC,
    LanePC,
    RejectedError,
    ServerSource,
    StandIn,
    ToolError,
    endpoint,
    proto,
)

PHONE_PORT = 8767
FORBIDDEN_PC_PORTS = {
    1234, 1235, 1236, 8080, 8081, 11434, 11435, 4173, 8765, 8767,
}
SERIAL = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
PORT = re.compile(r"[1-9][0-9]{0,4}\Z")
DEFAULT_SERVER = "http://127.0.0.1:1235/v1/chat/completions"

# Android's H5 + S5 + B5 sizes and optical values. Tk labels support font size
# and weight, but not letter tracking, tabular figures, or a fixed line height.
DIALOG_TYPE = {
    "H5": {"size": 21, "weight": "semibold", "leading": 1.15, "tracking": -0.01},
    "S5": {"size": 11, "weight": "normal", "leading": 1.25, "tracking": 0.02, "tnum": True},
    "B5": {"size": 17, "weight": "normal", "leading": 1.35, "tracking": 0.0},
}
DIALOG_INK = "#000000"
DIALOG_PAPER = "#FFFFFF"
DIALOG_ERROR = "#B00000"
DIALOG_SUCCESS = "#008000"


def _dialog_font_specs(available, heading_fallback, text_fallback):
    """Use installed families, or the platform's Tk heading/default fonts."""
    names = {name.casefold(): name for name in available}

    def pick(candidates, fallback):
        return next((names[name.casefold()] for name in candidates
                     if name.casefold() in names), fallback)

    title = pick(("Source Serif 4 Subhead SemiBold", "Source Serif 4 Subhead",
                  "Source Serif 4 SemiBold", "Source Serif 4",
                  "Newsreader SemiBold", "Newsreader", "Newsreader 72pt",
                  "Source Serif Pro", "Source Serif"), heading_fallback)
    # Tk has no semibold weight. Use the real cut when installed, else bold.
    title_weight = "normal" if "semibold" in title.casefold() else "bold"
    text = pick(("Source Serif 4 Text", "Source Serif 4", "Newsreader",
                 "Source Serif Pro", "Source Serif", "Inter"), text_fallback)
    small = pick(("Inter Medium", "Inter"), text_fallback)
    return {"title": (title, DIALOG_TYPE["H5"]["size"], title_weight),
            "small": (small, DIALOG_TYPE["S5"]["size"], DIALOG_TYPE["S5"]["weight"]),
            "body": (text, DIALOG_TYPE["B5"]["size"], DIALOG_TYPE["B5"]["weight"])}


def _dialog_fonts(root):
    from tkinter import font as tkfont
    specs = _dialog_font_specs(tkfont.families(root),
                               tkfont.nametofont("TkHeadingFont", root=root).actual("family"),
                               tkfont.nametofont("TkDefaultFont", root=root).actual("family"))
    return {role: tkfont.Font(root=root, family=family, size=size, weight=weight)
            for role, (family, size, weight) in specs.items()}


def _dialog_label(tk, parent, text, font, *, color=DIALOG_INK, wraplength=470):
    return tk.Label(parent, text=text, font=font, fg=color, bg=DIALOG_PAPER,
                    justify="left", anchor="w", wraplength=wraplength)


def _dialog_button(tk, parent, text, font, **options):
    return tk.Button(parent, text=text, font=font, fg=DIALOG_INK, bg=DIALOG_PAPER,
                     activeforeground=DIALOG_INK, activebackground=DIALOG_PAPER,
                     highlightbackground=DIALOG_PAPER, **options)


def _build_main_window(tk, root, status, computer_label, fonts, on_retry,
                       on_remove, on_stop):
    """A phone-left, computer-right band above a status row that takes spare space."""
    root.configure(bg=DIALOG_PAPER)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)
    root.minsize(600, 300)

    band = tk.Frame(root, bg=DIALOG_PAPER)
    band.grid(row=0, column=0, sticky="ew", padx=18, pady=(18, 10))
    band.columnconfigure(0, weight=1, uniform="device")
    band.columnconfigure(2, weight=1, uniform="device")

    def device_panel(column, name):
        panel = tk.Frame(band, bg=DIALOG_PAPER, highlightbackground=DIALOG_INK,
                         highlightthickness=1, bd=0)
        panel.grid(row=0, column=column, sticky="nsew")
        panel.columnconfigure(0, weight=1)
        name_label = _dialog_label(tk, panel, name, fonts["title"])
        name_label.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        panel.bind("<Configure>", lambda event: name_label.configure(
            wraplength=max(100, event.width - 32)))
        return panel

    phone_panel = device_panel(0, "Phone")
    link_state = tk.StringVar(value="USB-C\nWaiting")
    link_label = tk.Label(band, textvariable=link_state, font=fonts["small"],
                          fg=DIALOG_INK, bg=DIALOG_PAPER, justify="center",
                          anchor="center", width=18)
    link_label.grid(row=0, column=1, sticky="ns", padx=8)
    computer_panel = device_panel(2, computer_label)

    status_frame = tk.Frame(root, bg=DIALOG_PAPER, highlightbackground=DIALOG_INK,
                            highlightthickness=1, bd=0)
    status_frame.grid(row=1, column=0, sticky="nsew", padx=18, pady=(0, 10))
    status_frame.columnconfigure(0, weight=1)
    status_frame.rowconfigure(1, weight=1)
    _dialog_label(tk, status_frame, "STATUS", fonts["small"]).grid(
        row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
    status_label = tk.Label(status_frame, textvariable=status, font=fonts["body"],
                            fg=DIALOG_INK, bg=DIALOG_PAPER, justify="left", anchor="nw")
    status_label.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
    status_frame.bind("<Configure>", lambda event: status_label.configure(
        wraplength=max(100, event.width - 32)))

    controls = tk.Frame(root, bg=DIALOG_PAPER)
    controls.grid(row=2, column=0, sticky="ew", padx=18, pady=(0, 18))
    for column, (label, command) in enumerate((
        ("Try again", on_retry),
        ("Remove model copies", on_remove),
        ("Stop GPU Link", on_stop),
    )):
        controls.columnconfigure(column, weight=1)
        _dialog_button(tk, controls, label, fonts["small"], command=command).grid(
            row=0, column=column, sticky="ew", padx=(0 if column == 0 else 4,
                                                   0 if column == 2 else 4))
    return {"phone_panel": phone_panel, "link_label": link_label,
            "link_state": link_state, "computer_panel": computer_panel,
            "status_frame": status_frame, "status_label": status_label}


def _status_is_error(message: str) -> bool:
    """Reserve red for a reported failure, not for an unplug or a normal pause."""
    return bool(re.search(
        r"\b(failed|unavailable|rejected|declined|error|refused|unconfirmed)\b"
        r"|\bcould not\b|\bcannot\b|\bnot removed\b|\bstopped; retrying\b",
        message, re.IGNORECASE,
    ))


def _main_window_tone(online: bool, message: str) -> tuple[str, str, str]:
    """Return link words, link ink, and status ink from known runtime state."""
    if online:
        return ("USB-C\nConnected", DIALOG_SUCCESS,
                DIALOG_ERROR if _status_is_error(message) else DIALOG_INK)
    if _status_is_error(message):
        return "USB-C\nNeeds attention", DIALOG_ERROR, DIALOG_ERROR
    return "USB-C\nWaiting", DIALOG_INK, DIALOG_INK


class _DialogLifetime:
    """Cancel a dialog's pending Tk callbacks before destroying its window."""

    def __init__(self, top):
        self.top = top
        self.pending = set()
        self.closed = False

    def after(self, delay, callback):
        if self.closed:
            return

        def run():
            self.pending.discard(timer_id)
            if not self.closed:
                callback()

        timer_id = self.top.after(delay, run)
        self.pending.add(timer_id)

    def close(self):
        if self.closed:
            return
        self.closed = True
        for timer_id in tuple(self.pending):
            self.top.after_cancel(timer_id)
        self.pending.clear()
        self.top.destroy()


def _confirm_remove_model_copies(root, models_dir: Path, tk, clock=time.monotonic) -> bool:
    """A styled, guarded confirmation for this companion's marked downloads."""
    top = tk.Toplevel(root)
    top.title("Remove model copies?")
    top.transient(root)
    top.grab_set()
    top.configure(bg=DIALOG_PAPER)
    fonts = _dialog_fonts(root)
    _dialog_label(tk, top, "Remove model copies?", fonts["title"]).pack(
        padx=24, pady=(22, 10), anchor="w")
    _dialog_label(tk, top, f"Remove GPU Link's downloaded model files from {models_dir}?",
                  fonts["body"]).pack(padx=24, pady=(0, 8), anchor="w")
    _dialog_label(tk, top, "A model already running stays loaded.", fonts["small"]).pack(
        padx=24, pady=(0, 14), anchor="w")
    choice = {"remove": False}
    unblock = clock() + 0.7
    lifetime = _DialogLifetime(top)

    def finish(remove=False):
        if lifetime.closed or (remove and clock() < unblock):
            return
        choice["remove"] = remove
        lifetime.close()

    remove = _dialog_button(tk, top, "Remove copies", fonts["small"], state="disabled",
                            command=lambda: finish(True))
    deny = _dialog_button(tk, top, "Not now", fonts["small"], state="normal",
                          command=finish)
    remove.pack(side="right", padx=(0, 24), pady=(0, 18))
    deny.pack(side="right", padx=12, pady=(0, 18))
    deny.focus_set()

    def on_return(_event):
        finish(top.focus_get() == remove)
        return "break"

    top.bind("<Escape>", lambda event: finish())
    top.bind("<Return>", on_return)
    top.protocol("WM_DELETE_WINDOW", finish)
    lifetime.after(700, lambda: remove.configure(state="normal"))
    root.wait_window(top)
    return choice["remove"]


def _permission_identity_lines(args):
    """Show only a supplied phone name and an identified, active GPU."""
    lines = []
    phone = getattr(args, "phone_label", None)
    if isinstance(phone, str) and phone.strip() and phone.strip() != "OPOS phone":
        lines.append("Phone: " + phone.strip())
    gpu = getattr(getattr(args, "runtime", None), "gpu", None)
    if isinstance(gpu, dict) and gpu.get("backend") != "cpu":
        name = gpu.get("name")
        if isinstance(name, str) and name.strip() and name.strip() not in {"GPU", "Apple GPU", "Mac"}:
            lines.append("GPU: " + name.strip())
    return lines


MAC_MODEL_ID = "/usr/sbin/sysctl"
MAC_POWER = "/usr/bin/pmset"
_NOUN_CACHE: list[str] = []
_NOUN_LOCK = threading.Lock()


def _quiet_output(argv: list[str]) -> str:
    """One short local query; any failure reads as no answer."""
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                              timeout=2, check=False)
    except (OSError, subprocess.SubprocessError, ValueError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def computer_noun(system: str | None = None, model_id: str | None = None,
                  battery: bool | None = None) -> str:
    """Name this computer for people: "MacBook", "Mac" or "PC" (Windows or Linux).

    Apple silicon reports model IDs like "Mac17,9" for laptops and desktops alike, so a
    built-in battery is what marks a MacBook there. This is screen wording only; the wire
    label comes from gpu_link_autosetup.safe_label.
    main() warms the cached default once before any window or worker thread starts.
    """
    if system is None and model_id is None and battery is None:
        with _NOUN_LOCK:
            if not _NOUN_CACHE:
                _NOUN_CACHE.append(_detect_computer_noun(platform.system() or "", None, None))
            return _NOUN_CACHE[0]
    return _detect_computer_noun(system or platform.system() or "", model_id, battery)


def _detect_computer_noun(system: str, model_id: str | None, battery: bool | None) -> str:
    if system != "Darwin":
        noun = "PC"
    else:
        if model_id is None:
            model_id = _quiet_output([MAC_MODEL_ID, "-n", "hw.model"]).strip()
        if model_id.startswith("MacBook"):
            noun = "MacBook"
        else:
            if battery is None:
                battery = "InternalBattery" in _quiet_output([MAC_POWER, "-g", "batt"])
            noun = "MacBook" if battery else "Mac"
    return noun


class CompanionError(Exception):
    """A safe diagnostic that never includes a secret or subprocess output."""


class RetryLater(CompanionError):
    """A transport fault that should be retried while the phone is present."""


class GrantDeclined(CompanionError):
    """The computer's owner did not approve a transient grant."""


def valid_usb_serial(serial: str) -> bool:
    """Do not target adb's TCP or emulator transports as the selected phone."""
    return bool(SERIAL.fullmatch(serial)) and not (serial.startswith("emulator-") or
                                                    "._tcp" in serial or
                                                    re.search(r":\d+\Z", serial))


def authorized_devices(adb: str, runner=subprocess.run) -> list[tuple[str, bool]]:
    """List every authorized adb device and whether it has USB transport evidence."""
    try:
        result = runner([adb, "devices", "-l"], stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CompanionError("adb is unavailable; install or select Android platform tools") from error
    if result.returncode != 0:
        raise CompanionError("adb could not list phones; check Android platform tools")
    found = []
    for line in result.stdout.decode("utf-8", "replace").splitlines():
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "device":
            found.append((fields[0], any(field.startswith("usb:") for field in fields[2:])))
    return found


def select_serial(adb: str, runner=subprocess.run) -> str | None:
    found = authorized_devices(adb, runner)
    if not found:
        return None
    usb_serials = [serial for serial, usb in found if usb and valid_usb_serial(serial)]
    if len(usb_serials) > 1:
        raise CompanionError("More than one authorized USB phone is present; pass --serial")
    if not usb_serials:
        raise CompanionError("No authorized USB phone is present")
    return usb_serials[0]


def _dpapi(data: bytes, encrypt: bool) -> bytes:
    """Protect the Windows user's saved key with DPAPI, without extra packages."""
    if os.name != "nt":
        return data

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    source = ctypes.create_string_buffer(data)
    input_blob = Blob(len(data), ctypes.cast(source, ctypes.POINTER(ctypes.c_ubyte)))
    output_blob = Blob()
    crypt = ctypes.windll.crypt32.CryptProtectData if encrypt else ctypes.windll.crypt32.CryptUnprotectData
    crypt.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                      ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    crypt.restype = ctypes.c_int
    if not crypt(ctypes.byref(input_blob), None, None, None, None, 1, ctypes.byref(output_blob)):
        raise CompanionError("Windows key protection failed")
    try:
        return ctypes.string_at(output_blob.data, output_blob.size)
    finally:
        free = ctypes.windll.kernel32.LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(ctypes.cast(output_blob.data, ctypes.c_void_p))


class KeyStore:
    def __init__(self, directory: Path, serial: str):
        name = hashlib.sha256(serial.encode("utf-8")).hexdigest()[:24] + ".key"
        self.directory = directory
        self.path = directory / name

    def load(self) -> bytes | None:
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
            fd = os.open(self.path, flags)
        except FileNotFoundError:
            return None
        except OSError as error:
            raise CompanionError("Could not open the saved pairing") from error
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 4096:
                raise CompanionError("Saved pairing is not a regular key file")
            if os.name != "nt" and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid()):
                raise CompanionError("Saved pairing must be owned by this user with mode 0600")
            stored = handle.read(4097)
        key = _dpapi(stored, False)
        if len(key) != proto.KEY_BYTES:
            raise CompanionError("Saved pairing is invalid; use owner recovery")
        return key

    def save_first_allow(self, key: bytes) -> None:
        if len(key) != proto.KEY_BYTES:
            raise CompanionError("Invalid pairing key")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        stored = _dpapi(key, True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
        try:
            fd = os.open(self.path, flags, 0o600)
        except FileExistsError as error:
            raise CompanionError("Saved pairing already exists; it was not replaced") from error
        try:
            with os.fdopen(fd, "wb") as handle:
                if os.name != "nt":
                    os.fchmod(handle.fileno(), 0o600)
                handle.write(stored)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            self.path.unlink(missing_ok=True)
            raise CompanionError("Could not save approved pairing") from error

    def reset(self) -> bool:
        """Remove only this serial's saved key while its instance lock is held."""
        try:
            info = self.path.lstat()
            if not stat.S_ISREG(info.st_mode):
                raise CompanionError("Saved pairing is not a regular key file")
            if os.name != "nt" and (stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.getuid()):
                raise CompanionError("Saved pairing must be owned by this user with mode 0600")
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False
        except OSError as error:
            raise CompanionError("Could not remove this phone's saved pairing") from error


def parse_enrol_reply(raw: bytes) -> tuple[int, str]:
    if len(raw) > 8192 or b"\r\n\r\n" not in raw:
        raise CompanionError("Phone enrolment reply was incomplete")
    head, body = raw.split(b"\r\n\r\n", 1)
    lines = head.split(b"\r\n")
    match = re.fullmatch(rb"HTTP/1\.[01] ([1-5][0-9]{2}) [\x20-\x7e]*", lines[0])
    if not match:
        raise CompanionError("Phone enrolment reply was invalid")
    lengths = [line.split(b":", 1)[1].strip() for line in lines[1:]
               if line.lower().startswith(b"content-length:")]
    if len(lengths) != 1 or not lengths[0].isdigit() or int(lengths[0]) != len(body):
        raise CompanionError("Phone enrolment reply length was invalid")
    try:
        value = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise CompanionError("Phone enrolment reply was invalid") from error
    if not isinstance(value, dict) or set(value) != {"state"} or not isinstance(value["state"], str):
        raise CompanionError("Phone enrolment reply was invalid")
    return int(match.group(1)), value["state"]


def listener_owned_by_adb(port: int, adb: str) -> bool:
    """Require a loopback listener owned by the selected adb executable."""
    selected = shutil.which(adb)
    if selected is None:
        return False
    expected = Path(selected).resolve()
    try:
        if sys.platform == "win32":
            script = (
                "$ErrorActionPreference='Stop';"
                f"$p={port};"
                "Get-NetTCPConnection -State Listen -LocalPort $p | ForEach-Object {"
                "$owner=Get-Process -Id $_.OwningProcess;"
                "Write-Output ($_.LocalAddress+'|'+$owner.Path)"
                "}"
            )
            result = subprocess.run(
                ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True, timeout=5, check=False,
            )
            if result.returncode != 0:
                return False
            listeners = [line.split("|", 1) for line in result.stdout.decode(
                "utf-8", "replace").splitlines() if "|" in line]
            return bool(listeners) and all(
                address in ("127.0.0.1", "::1")
                and os.path.normcase(str(Path(path).resolve())) == os.path.normcase(str(expected))
                for address, path in listeners
            )
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpn"],
            capture_output=True, timeout=5, check=False,
        )
        if result.returncode != 0:
            return False
        owners = set()
        pid = None
        for line in result.stdout.decode("utf-8", "replace").splitlines():
            if line.startswith("p") and line[1:].isdigit():
                pid = line[1:]
            elif line.startswith("n") and pid is not None:
                address = line[1:].rsplit(":", 1)[0]
                if address not in ("127.0.0.1", "[::1]"):
                    return False
                owners.add(pid)
        if not owners:
            return False
        for owner in owners:
            binary = subprocess.run(
                ["lsof", "-nP", "-a", "-p", owner, "-d", "txt", "-Fn"],
                capture_output=True, timeout=5, check=False,
            )
            paths = [Path(line[1:]).resolve() for line in binary.stdout.decode(
                "utf-8", "replace").splitlines() if line.startswith("n")]
            if binary.returncode != 0 or expected not in paths:
                return False
        return True
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return False


class AdbBridge:
    def __init__(self, adb: str, serial: str, runner=subprocess.run,
                 owner_checker=listener_owned_by_adb):
        self.adb, self.serial, self.runner = adb, serial, runner
        self.owner_checker = owner_checker
        self.port: int | None = None
        self.provisional_port: int | None = None

    def call(self, *args: str, input_bytes: bytes | None = None, timeout: int = 5) -> bytes:
        try:
            result = self.runner([self.adb, *args], input=input_bytes, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            raise RetryLater("adb is unavailable or timed out") from error
        if result.returncode != 0:
            raise RetryLater("adb command failed; check device authorization and phone tools")
        return result.stdout

    def authorized(self) -> bool:
        output = self.call("devices", "-l").decode("utf-8", "replace")
        return any(fields[0] == self.serial and fields[1] == "device"
                   and any(field.startswith("usb:") for field in fields[2:])
                   for line in output.splitlines()
                   if len(fields := line.split()) >= 3)

    def _listed(self, port: int) -> bool:
        output = self.call("forward", "--list").decode("utf-8", "replace")
        expected = [self.serial, f"tcp:{port}", f"tcp:{PHONE_PORT}"]
        return any(line.split() == expected for line in output.splitlines())

    def create_forward(self) -> int:
        self.remove_own_forward()
        if self.port is not None or self.provisional_port is not None:
            raise RetryLater("Waiting to clean up the previous adb forward")
        for _ in range(8):
            output = self.call("-s", self.serial, "forward", "tcp:0", f"tcp:{PHONE_PORT}")
            value = output.decode("ascii", "replace").strip()
            if not PORT.fullmatch(value) or int(value) > 65535:
                raise CompanionError("adb did not report a usable forward port")
            port = int(value)
            self.provisional_port = port
            try:
                if not self._listed(port):
                    raise CompanionError("adb forward could not be verified")
                if port in FORBIDDEN_PC_PORTS:
                    self.remove_own_forward()
                    if self.provisional_port is not None:
                        raise RetryLater("Waiting to clean up a reserved local port")
                    continue
                if not self.owner_checker(port, self.adb):
                    raise CompanionError(
                        "Could not verify that the adb forward is a loopback listener "
                        "owned by the selected adb executable. "
                        "This is a visible setup failure, not a queued computer answer. "
                        "If an adb server is already running, start GPU Link again so "
                        "it can detect that server's executable, or pass --adb pointing "
                        "at it. If inspection tools are unavailable, install them and retry."
                    )
                self.port, self.provisional_port = port, None
                return port
            except CompanionError:
                self.remove_own_forward()
                raise
        raise CompanionError("adb chose only reserved local ports")

    def forward_present(self) -> bool:
        if self.port is None:
            return False
        try:
            return self._listed(self.port) and self.owner_checker(self.port, self.adb)
        except RetryLater:
            return False

    def remove_own_forward(self) -> None:
        for name in ("port", "provisional_port"):
            port = getattr(self, name)
            if port is None:
                continue
            try:
                if self._listed(port):
                    self.call("-s", self.serial, "forward", "--remove", f"tcp:{port}")
                setattr(self, name, None)
            except CompanionError:
                # Keep ownership recorded and retry when adb becomes available.
                pass

    def launch_models(self) -> None:
        self.call("-s", self.serial, "shell", "am", "start", "-n",
                  "os.opos.launcher/.MainActivity", timeout=8)

    def enrol(self, pc: PC) -> tuple[int, str]:
        # The key travels only as stdin to the phone's own loopback nc command.
        raw = self.call("-s", self.serial, "shell", "-T", "nc", "127.0.0.1",
                        str(PHONE_PORT), input_bytes=pc.enrol_request(), timeout=8)
        return parse_enrol_reply(raw)


def authenticated_idle(pc: PC) -> bool:
    """A signed status reply proves saved trust; a pending key never does."""
    pc.hello()
    try:
        status, _ = pc.status(state="idle")
    except RejectedError:
        pc.hello()
        try:
            status, _ = pc.status(state="idle")
        except RejectedError:
            return False
    return status == 200


def model_server_listening(url: str) -> bool:
    """Check local TCP availability while an already checked worker is running."""
    host, port, _ = endpoint(url)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def model_server_answers(url: str, timeout: float = 1.5) -> bool:
    """True when the model server replies to a small HTTP request in time.

    A stopped or hung server still accepts TCP connections, so listening alone does not
    prove it can stream again. /health is llama.cpp's; any reply below 500 also counts.
    """
    host, port, _ = endpoint(url)
    connection = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        connection.request("GET", "/health", headers=server_auth_headers())
        response = connection.getresponse()
        response.read(1024)
        return response.status < 500
    except (OSError, http.client.HTTPException, ValueError):
        return False
    finally:
        connection.close()


def model_server_preflight(url: str, model: str, cancelled=lambda: False,
                           first_event_timeout: float = 90,
                           completion_timeout: float = 10,
                           retry_on_timeout: bool = False) -> bool | None:
    """Require an exact-model choice finish and SSE DONE from the chat route."""
    host, port, parsed = endpoint(url)
    connection_type = (http.client.HTTPSConnection if parsed.scheme == "https"
                       else http.client.HTTPConnection)
    connection = connection_type(host, port, timeout=2)
    target = parsed.path + ("?" + parsed.query if parsed.query else "")
    request = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply OK."}],
        "stream": True,
        "stream_options": {"include_usage": True},
        "max_tokens": 1,
    }
    effort = os.environ.get("OPOS_GPU_LINK_REASONING_EFFORT", "none").strip()
    if effort and effort != "default":
        request["reasoning_effort"] = effort
    payload = json.dumps(request).encode()
    watchdog_stop = threading.Event()
    timed_out = threading.Event()
    watchdog = None
    deadline = None
    try:
        connection.connect()  # The two-second limit applies only to TCP connect.
        if cancelled():
            return False
        connection.sock.settimeout(first_event_timeout)
        wire = connection.sock  # HTTPResponse may take ownership and clear connection.sock.
        connection.request("POST", target, payload, {
            "Content-Type": "application/json", "Accept": "text/event-stream",
            "Accept-Encoding": "identity", **server_auth_headers(),
        })
        deadline = [time.monotonic() + first_event_timeout]

        def watch_wait():
            while not watchdog_stop.wait(0.1):
                if cancelled() or time.monotonic() >= deadline[0]:
                    if not cancelled():
                        timed_out.set()
                    try:
                        wire.shutdown(socket.SHUT_RDWR)
                    except (OSError, AttributeError):
                        pass
                    wire.close()
                    connection.close()
                    return

        watchdog = threading.Thread(target=watch_wait, name="opos-preflight-timeout", daemon=True)
        watchdog.start()
        with connection.getresponse() as response:
            if response.status != 200 or response.getheader("Content-Encoding") not in (None, "identity"):
                return False
            if response.getheader("Content-Type", "").split(";", 1)[0].strip() != "text/event-stream":
                return False
            total = 0
            saw_finish = False
            first_event = True
            while time.monotonic() < deadline[0] and total <= 65536 and not cancelled():
                line = response.readline(4097)
                total += len(line)
                if not line:
                    return None if retry_on_timeout and timed_out.is_set() and not cancelled() else False
                if len(line) > 4096 or total > 65536:
                    return False
                if not line.startswith(b"data:"):
                    continue
                event = line[5:].strip()
                if event == b"[DONE]":
                    return saw_finish and not cancelled()
                value = json.loads(event)
                if not isinstance(value, dict):
                    return False
                if first_event:
                    first_event = False
                    deadline[0] = time.monotonic() + completion_timeout
                    wire.settimeout(completion_timeout)
                if "model" in value and value["model"] != model:
                    return False
                if "choices" not in value:
                    if not isinstance(value.get("usage"), dict):
                        return False
                    continue  # A usage-only event cannot prove a finish.
                choices = value["choices"]
                if value.get("model") != model or not isinstance(choices, list):
                    return False
                if not choices:
                    continue
                choice = choices[0]
                if (not isinstance(choice, dict) or type(choice.get("index")) is not int
                        or choice["index"] != 0):
                    return False
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    return False
                content = delta.get("content")
                if content is not None and not isinstance(content, str):
                    return False
                finish = choice.get("finish_reason")
                if finish is not None and not isinstance(finish, str):
                    return False
                if finish in ("stop", "length"):
                    saw_finish = True
                elif finish is not None:
                    return False
            return None if retry_on_timeout and not cancelled() and (
                timed_out.is_set() or time.monotonic() >= deadline[0]) else False
    except (OSError, ValueError, http.client.HTTPException, TypeError, AttributeError):
        return None if retry_on_timeout and not cancelled() and (
            timed_out.is_set() or deadline is not None and time.monotonic() >= deadline[0]) else False
    finally:
        watchdog_stop.set()
        connection.close()
        if watchdog is not None:
            watchdog.join(1)


class LazyServerSource:
    """Keep a lane warm and responsive while its first SSE preflight loads a model."""

    def __init__(self, job, url, model, checked, checked_lock, retry_budget=None):
        self.job, self.url, self.model = job, url, model
        self.checked, self.checked_lock = checked, checked_lock
        self.retry_budget = retry_budget
        self.stop = threading.Event()
        self.lock = threading.Lock()
        self.source = None
        self.error = False
        self.thread = threading.Thread(target=self._prepare, name="opos-extra-model-preflight", daemon=True)
        self.thread.start()

    @property
    def error_code(self):
        with self.lock:
            return getattr(self.source, "error_code", "server")

    @property
    def warming(self):
        with self.lock:
            return self.source is None and not self.error and not self.stop.is_set()

    def _prepare(self):
        with self.checked_lock:
            ready = self.model in self.checked
        while not ready and not self.stop.is_set():
            try:
                result = model_server_preflight(self.url, self.model, cancelled=self.stop.is_set,
                                                retry_on_timeout=True)
            except (OSError, ValueError, TypeError, ToolError):
                result = False
            if result is None:
                self.stop.wait(1)
                continue  # A slow first load stays in the loading state, never a lane error.
            ready = result
            break
        if ready and not self.stop.is_set():
            with self.checked_lock:
                self.checked.add(self.model)
        if self.stop.is_set():
            return
        if not ready:
            with self.lock:
                self.error = True
            return
        try:
            source = (ServerSource(self.job, self.url, self.model, self.retry_budget)
                      if self.retry_budget is not None else ServerSource(self.job, self.url, self.model))
        except (OSError, ValueError, TypeError, ToolError):
            with self.lock:
                self.error = True
            return
        with self.lock:
            if self.stop.is_set():
                source.close()
            else:
                self.source = source

    def snapshot(self):
        with self.lock:
            source, error = self.source, self.error
        if source is not None:
            snapshot = source.snapshot()
            if snapshot[-1]:  # the stream failed: do not trust the earlier "model is ready" check
                with self.checked_lock:
                    self.checked.discard(self.model)
            return snapshot
        return self.job["partial"].encode(), False, "stop", None, error

    def close(self):
        self.stop.set()
        with self.lock:
            source = self.source
        if source is not None:
            source.close()
        self.thread.join(4)


class FailedSource:
    """Fail only a lane whose signed offer no longer matches its advertised model."""

    error_code = "model"

    def __init__(self, job):
        self.partial = job["partial"].encode()

    def snapshot(self):
        return self.partial, False, "stop", None, True

    def close(self):
        pass


def advertise_runtime_models(pc, models, runtime=None):
    """Send one signed model snapshot and return its accepted revision."""
    revision = -1
    payload_models = [dict(model) for model in models]
    if runtime is not None:
        with runtime.state_lock:
            for model in payload_models:
                lane = runtime.lane(model["id"])
                if lane is not None:
                    model.update(label=lane["label"], maker=lane["maker"])
            revision = runtime.revision
    advertisement = proto.dumps({"models": payload_models})
    proto.parse_advertise(advertisement)
    try:
        status, value = pc.send("POST", "/v1/advertise", advertisement)
    except RejectedError:
        if not authenticated_idle(pc):
            raise ToolError("saved key not accepted") from None
        try:
            status, value = pc.send("POST", "/v1/advertise", advertisement)
        except RejectedError:
            status, value = 400, {"error": "request"}
    enabled = status == 200 and value.get("accepted") == len(payload_models)
    if not enabled and not (status == 400 and value.get("error") == "request"):
        raise ToolError("extra model advertisement refused")
    return enabled, revision


class RuntimeSource:
    """Observe one terminal owned-lane attempt without changing signed work."""

    def __init__(self, factory, runtime, lane_id, job, ready=lambda: True):
        self.factory, self.runtime, self.lane_id, self.job = factory, runtime, lane_id, job
        self.source, self.ready = None, ready
        self.closed = self.recorded = False
        self.crash_version = runtime.crashes.get(lane_id, 0)
        self.code = None

    @property
    def warming(self):
        return self.source is None or getattr(self.source, "warming", False)

    @property
    def error_code(self):
        return self.code or getattr(self.source, "error_code", "server")

    def snapshot(self):
        if self.source is None:
            plan = self.runtime.fallback_plan
            if plan is not None and plan.status(self.lane_id) == "fallback_failed":
                self.code = "fallback_failed"
                return self.job["partial"].encode(), True, "stop", None, True
            if self.closed or self.runtime.stopping.is_set():
                return self.job["partial"].encode(), False, "stop", None, False
            if self.lane_id in self.runtime.pending or not self.ready():
                return self.job["partial"].encode(), False, "stop", None, False
            try:
                self.source = self.factory()
            except (OSError, ValueError, TypeError, ToolError):
                self.source = FailedSource(self.job)
                self.source.error_code = "model_start"
            self.crash_version = self.runtime.crashes.get(self.lane_id, 0)
        snapshot = self.source.snapshot()
        crashed = self.runtime.crashes.get(self.lane_id, 0) != self.crash_version
        if crashed and not snapshot[-1]:
            snapshot = (*snapshot[:4], True)
        if snapshot[-1] and not self.recorded and not self.closed:
            self.recorded = True
            code = getattr(self.source, "error_code", "server")
            reason = ("crash" if crashed else "garbled" if code == "garbled" else
                      "model_start" if code == "model_start" else
                      "model_start" if isinstance(self.source, LazyServerSource) and self.source.source is None
                      else "stream_error")
            status = self.runtime.record_failure(self.lane_id, self.job, reason)
            if status == "fallback_failed":
                self.code = "fallback_failed"
        return snapshot

    def close(self):
        self.closed = True
        if self.source is not None:
            self.source.close()


WORKER_STOP_BUDGET = 6.0   # one shared deadline for the worker and every lane, not 6 s each
LANE_JOIN_BUDGET = 5.0


def join_within(threads, budget, skip=None, clock=time.monotonic):
    """Join several threads against a single shared deadline."""
    deadline = clock() + budget
    for thread in threads:
        if thread is None or thread is skip or not thread.is_alive():
            continue
        thread.join(max(0.0, deadline - clock()))


class ConsoleStatus:
    """Print only deduplicated companion-owned status messages."""

    def __init__(self):
        self.last = None

    def set(self, message: str) -> None:
        if message != self.last:
            print("GPU Link: " + message, flush=True)
            self.last = message


def presenter_error(error: Exception) -> str:
    """Keep expected setup failures to one actionable status line."""
    if isinstance(error, OSError):
        return "Error: Pairing folder is unavailable. Check file access on this computer, then retry."
    message = str(error).strip()
    if not message:
        return "Error: GPU Link stopped. Restart it, then retry."
    if message.startswith("Error:"):
        return message
    if "already running for this phone" in message:
        return "Error: GPU Link is already running for this phone. Stop the other copy, then retry."
    if "More than one authorized USB phone" in message:
        return "Error: More than one USB phone is ready. Unplug the extra phone, then retry."
    if "adb is unavailable" in message or "adb not found" in message:
        return "Error: USB tools are missing. Install Android platform tools, then retry."
    if "adb" in message or "forward" in message:
        return "Error: USB link failed. Check the cable and USB approval, then retry."
    if "directory" in message or "key file" in message:
        return "Error: Pairing folder is unavailable. Check its permissions, then retry."
    if "pairing" in message.lower() or "key" in message.lower():
        return "Error: Pairing could not continue. Check the phone, then retry."
    if message.startswith("Phone enrolment reply"):
        return "Error: Phone did not reply. Check the cable and phone, then retry."
    return f"Error: {message.rstrip('.')}. Check setup, then retry."


class InstanceGuard:
    """Hold a per-user, per-phone lock until the companion exits."""

    def __init__(self, directory: Path, serial: str):
        self.fd = None
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise CompanionError("Pairing directory must be a local directory")
        name = hashlib.sha256(serial.encode()).hexdigest()[:24] + ".lock"
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(directory / name, flags, 0o600)
            if os.name == "nt":
                import msvcrt
                if os.fstat(fd).st_size == 0:
                    os.write(fd, b"0")
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                os.fchmod(fd, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.fd = fd
        except (OSError, ValueError) as error:
            if "fd" in locals():
                os.close(fd)
            raise CompanionError("GPU Link is already running for this phone, or its lock is unavailable") from error

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class Companion:
    def __init__(self, args, root=None, tk=None, headless=False):
        self.args, self.root, self.tk, self.headless = args, root, tk, headless
        self.bridge = AdbBridge(args.adb, args.serial)
        self.keys = KeyStore(args.key_dir, args.serial)
        self.clock = time.monotonic
        self.events = queue.SimpleQueue()
        self.wake = threading.Event()
        if headless:
            self.status = ConsoleStatus()
            self.status.set("Waiting for the phone on USB.")
        else:
            self.status = tk.StringVar(value="Waiting for the phone on USB.")
            self.main_window = _build_main_window(
                tk, root, self.status, computer_noun(), _dialog_fonts(root),
                self.retry, self.remove_model_copies, self.stop,
            )
            root.protocol("WM_DELETE_WINDOW", self.stop)
        self.running = True
        self.online = False
        if not headless:
            self.status.trace_add("write", lambda *_: self._refresh_main_window())
            self._refresh_main_window()
        # Starting a headless process is a grant for this run. --always-allow
        # retains that grant across an extended unplug, without a computer dialog.
        self.granted = bool(headless or args.always_allow)
        self.detached_at: float | None = None
        self.blocked_until_detach = False
        self.worker: threading.Thread | None = None
        self.worker_stop: threading.Event | None = None
        self.lane_workers: tuple[threading.Thread, ...] = ()
        self.next_try = 0.0
        self.pending_key: bytes | None = None
        self.cleanup_ok = True
        self.session_pc: PC | None = None
        self.session_launch_failed = False
        self.preflight_thread: threading.Thread | None = None
        self.preflight_done: threading.Event | None = None
        self.preflight_cancel: threading.Event | None = None
        self.preflight_result = False
        self.retry_delay = 3
        self.extra_checked: set[str] = set()
        self.extra_checked_lock = threading.Lock()

    def permission(self) -> bool:
        if self.headless:
            return False  # A headless transient grant cannot silently renew.
        if not self.link_present():
            return False
        noun = computer_noun()
        top = self.tk.Toplevel(self.root)
        top.title(f"Let this phone use your {noun}'s GPU?")
        top.transient(self.root)
        top.grab_set()
        top.configure(bg=DIALOG_PAPER)
        fonts = _dialog_fonts(self.root)
        _dialog_label(self.tk, top, f"Let this phone use your {noun}'s GPU?", fonts["title"]).pack(
            padx=24, pady=(22, 10), anchor="w")
        for line in _permission_identity_lines(self.args):
            _dialog_label(self.tk, top, line, fonts["small"]).pack(
                padx=24, pady=(0, 3), anchor="w")
        for index, line in enumerate((
                f"The phone can use this {noun}'s GPU while the cable is plugged in.",
                f"This {noun} can see your questions and the answers.",
                f"A copy of the model file stays on this {noun} until you remove it.",
        )):
            _dialog_label(self.tk, top, line, fonts["body"]).pack(
                padx=24, pady=(10 if index == 0 else 0, 6), anchor="w")
        _dialog_label(self.tk, top,
                      "Unplug to pause. Access ends after 2 minutes unplugged or when you choose Stop GPU Link.",
                      fonts["small"]).pack(padx=24, pady=(8, 14), anchor="w")
        choice = {"allowed": False}
        unblock = self.clock() + 0.7
        lifetime = _DialogLifetime(top)

        def finish(allowed=False):
            if lifetime.closed or (allowed and self.clock() < unblock):
                return
            choice["allowed"] = allowed and self.link_present()
            lifetime.close()

        def still_attached():
            if not self.link_present():
                lifetime.close()
            else:
                lifetime.after(1000, still_attached)

        allow = _dialog_button(self.tk, top, "Allow this phone", fonts["small"], state="disabled",
                               command=lambda: finish(True))
        deny = _dialog_button(self.tk, top, "Not now", fonts["small"], state="normal",
                              command=finish)
        allow.pack(side="right", padx=(0, 24), pady=(0, 18))
        deny.pack(side="right", padx=12, pady=(0, 18))
        deny.focus_set()

        def on_return(_event):
            finish(top.focus_get() == allow)
            return "break"

        top.bind("<Escape>", lambda event: finish())
        top.bind("<Return>", on_return)
        top.protocol("WM_DELETE_WINDOW", finish)
        lifetime.after(700, lambda: allow.configure(state="normal"))
        lifetime.after(1000, still_attached)
        self.root.wait_window(top)
        return choice["allowed"]

    def wait_for_phone_allow(self, pc: PC) -> bool:
        code = proto.code(pc.label, pc.key)
        deadline = self.clock() + 60
        if self.headless:
            self.status.set(f"Compare code {code[:3]} {code[3:]} on the phone. Tap Allow there.")
            while self.running and self.clock() < deadline:
                if not self.link_present():
                    return False
                try:
                    if authenticated_idle(pc):
                        return self.running and self.clock() < deadline and self.link_present()
                except (OSError, ToolError, CompanionError):
                    pass
                self.wake.wait(min(1, max(0, deadline - self.clock())))
                self.wake.clear()
            return False
        top = self.tk.Toplevel(self.root)
        noun = computer_noun()
        top.title(f"Pair this {noun}?")
        top.transient(self.root)
        top.grab_set()
        top.configure(bg=DIALOG_PAPER)
        fonts = _dialog_fonts(self.root)
        _dialog_label(self.tk, top, f"Pair this {noun}?", fonts["title"]).pack(
            padx=24, pady=(22, 8), anchor="w")
        _dialog_label(self.tk, top, "Compare this code with the phone before you allow.",
                      fonts["body"]).pack(padx=24, pady=(0, 12), anchor="w")
        _dialog_label(self.tk, top, "Pairing code", fonts["small"]).pack(
            padx=24, pady=(0, 4), anchor="w")
        _dialog_label(self.tk, top, f"{code[:3]} {code[3:]}", fonts["title"]).pack(
            padx=24, pady=(0, 6), anchor="w")
        countdown = _dialog_label(self.tk, top, "60 seconds left", fonts["small"])
        countdown.pack(padx=24, pady=(0, 12), anchor="w")
        _dialog_label(self.tk, top,
                      f"If allowed, this {noun} can see your questions and the answers. A model file stays here.",
                      fonts["body"]).pack(padx=24, pady=(0, 8), anchor="w")
        note = _dialog_label(self.tk, top, f"On the phone, tap Allow this {noun}.",
                             fonts["small"])
        note.pack(padx=24, pady=(0, 14), anchor="w")
        accepted = {"yes": False}
        lifetime = _DialogLifetime(top)

        def close():
            lifetime.close()

        def probe():
            if not self.link_present():
                note.configure(text="Error: Phone not ready. Check the cable and USB access.", fg=DIALOG_ERROR)
                countdown.configure(text="")
                lifetime.after(5000, close)
                return
            if self.clock() >= deadline:
                note.configure(text="Error: Pairing expired. Wait for a new code on the phone.",
                               fg=DIALOG_ERROR)
                countdown.configure(text="Expired", fg=DIALOG_ERROR)
                lifetime.after(5000, close)
                return
            countdown.configure(text=f"{max(1, int(deadline - self.clock() + 0.999))} seconds left")
            try:
                if authenticated_idle(pc):
                    accepted["yes"] = self.running and self.clock() < deadline and self.link_present()
                    close()
                    return
            except (OSError, ToolError, CompanionError):
                pass
            lifetime.after(1000, probe)

        deny = _dialog_button(self.tk, top, "Not now", fonts["small"], command=close)
        deny.pack(padx=24, pady=(0, 18), anchor="e")
        deny.focus_set()
        top.bind("<Escape>", lambda event: close())
        top.bind("<Return>", lambda event: close())
        top.protocol("WM_DELETE_WINDOW", close)
        lifetime.after(750, probe)
        self.root.wait_window(top)
        return accepted["yes"]

    def link_present(self) -> bool:
        try:
            return self.bridge.authorized() and self.bridge.forward_present()
        except CompanionError:
            return False

    def ensure_permission(self) -> None:
        if self.granted:
            return
        if self.headless:
            raise GrantDeclined(f"Error: {computer_noun()} access expired. Restart GPU Link to allow access again.")
        self.granted = self.permission()
        if not self.granted:
            raise GrantDeclined(f"Error: {computer_noun()} access was declined. Replug to try again.")

    def _forget_extra_checks(self) -> None:
        """Drop the "model already verified" cache: LM Studio may have unloaded a model, or the
        phone restarted, since the last session."""
        checked = getattr(self, "extra_checked", None)
        if checked is not None:
            with getattr(self, "extra_checked_lock", threading.Lock()):
                checked.clear()

    def _stop_worker(self) -> None:
        self.generation = getattr(self, "generation", 0) + 1
        if self.worker_stop is not None:
            self.worker_stop.set()
        lanes = tuple(getattr(self, "lane_workers", ()))
        # One shared deadline: the old sequential joins could stall a replug for 6 s x (1 + lanes).
        join_within([self.worker, *lanes], WORKER_STOP_BUDGET, skip=threading.current_thread())
        if self.worker is not None and not self.worker.is_alive() and not any(
                lane.is_alive() for lane in lanes):
            self.worker = None
            self.worker_stop = None
            self.lane_workers = ()
            self._forget_extra_checks()

    def _workers_alive(self) -> bool:
        lanes = tuple(getattr(self, "lane_workers", ()))
        return (self.worker is not None and self.worker.is_alive() and
                all(lane.is_alive() for lane in lanes))

    def _start_worker(self, pc: PC) -> None:
        if not self.running:
            return
        self.generation = getattr(self, "generation", 0) + 1
        generation = self.generation
        self.lane_workers = ()  # never inherit a previous session's (dead) lane threads
        self._forget_extra_checks()
        stop = threading.Event()
        if not hasattr(self, "guard_budgets"):
            self.guard_budgets = {}
        main_budget = self.guard_budgets.setdefault("main", GuardRetryBudget())
        runtime = getattr(self.args, "runtime", None)
        # Resolve the served model label for every status, including startup,
        # reconnects, a lead-only show, and a later fallback swap.
        def lead_label():
            lane = runtime.lane(self.args.model) if runtime is not None else None
            if lane is None:
                return None
            try:
                from gpu_link_autosetup import served_model_label
            except ImportError:
                label = lane.get("lead_label") or lane.get("label")
                return label if proto.valid_model_label(label) else None
            return served_model_label(lane.get("lead_label"), lane.get("label"))
        pc.lead_label_source = lead_label
        def source(job):
            if runtime is not None and runtime.lane(self.args.model) is not None:
                def build():
                    lane = runtime.lane(self.args.model)
                    return ServerSource(job, lane["url"], lane["id"], main_budget)
                return RuntimeSource(build, runtime, self.args.model, job)
            return ServerSource(job, self.args.server, self.args.model, main_budget)

        def main_ready():
            """A held answer resumes once the lead model server answers again."""
            if runtime is not None and self.args.model in runtime.pending:
                return False
            lane = runtime.lane(self.args.model) if runtime is not None else None
            return model_server_answers(lane["url"] if lane is not None else self.args.server)
        extra_models = getattr(self.args, "extra_models", [])

        def emit(message):
            if message == "Status ready":
                line = "Ready for questions on the phone."
            elif message == "Status busy":
                line = "Answer in progress."
            elif message == "Status warming":
                line = "Loading the model."
            elif message.startswith("Work received"):
                match = re.search(r"partial (\d+) bytes", message)
                line = "Answer resumed." if match and int(match.group(1)) else "Answer started."
            elif message == "Answer held: model server recovering":
                line = "Answer paused. Waiting for the model server."
            elif message == "Model server answering again; resuming":
                line = "Model server recovered. Resuming the answer."
            elif message.startswith("Answer stopped: chat-completions server error"):
                line = "Error: The model could not finish. Check the model server, then retry."
            elif message.startswith("Answer cancelled"):
                line = "Answer stopped on the phone."
            else:
                return  # No question, answer, token, path, key or raw error in status.
            self.events.put((generation, line))

        advertise_lock = threading.RLock()
        def advertise():
            """Tell the phone which extra computer models exist. True when it accepted them."""
            with advertise_lock:
                enabled, revision = advertise_runtime_models(pc, extra_models, runtime)
                if enabled and runtime is not None:
                    self.guard_advertised_revision = revision
                return enabled

        self.guard_refresh = threading.Event()
        self.guard_advertised_revision = -1
        self.guard_advertise = advertise

        def runtime_event(event):
            self._forget_extra_checks()
            if event["status"] == "fallback" and extra_models:
                self.guard_refresh.set()
            words = {
                "restart_pending": "Model server stopped. Restarting it.",
                "restarted": "Model server restarted.",
                "fallback": "A model is ready after recovery.",
                "gave_up": "Error: Model server stopped. Check its log, then retry.",
                "port_busy": "Error: Model port is busy. Free it, then retry.",
                "ownership_refused": "Error: Model server changed. Check the running server.",
                "cleanup_failed": "Error: Model server did not stop. Check the running server.",
                "fallback_failed": "Error: The replacement model did not start. Check its log.",
                "supervisor_error": "Error: Model server check failed. Check its log.",
            }
            line = words.get(event["status"])
            if line:
                self.events.put((generation, line))

        advertised = threading.Event()

        def phone_restarted(_epoch):
            """A new signing epoch means the phone backend restarted and forgot the advertisement."""
            if not advertised.is_set() or stop.is_set():
                return
            try:
                if not advertise():  # a restarted phone that now refuses the route has no extra models
                    raise ToolError("extra model advertisement refused")
            except (OSError, ToolError, ValueError):
                self.events.put((generation, "Phone restarted. Reconnecting the models."))
                stop.set()  # the session restarts through the normal reconnect path

        def run():
            lane_threads = []
            try:
                if runtime is not None:
                    runtime.listen(runtime_event)
                enabled = advertise() if extra_models else False
                if stop.is_set() or self.generation != generation:
                    return  # stopped while advertising: start no lanes, enter no reactor
                if enabled:
                    if not hasattr(self, "extra_checked"):
                        self.extra_checked, self.extra_checked_lock = set(), threading.Lock()
                    pc.on_new_epoch = phone_restarted
                    advertised.set()
                    for index, model in enumerate(extra_models, 1):
                        lane_pc = LanePC(f"{pc.host}:{pc.port}", pc.key, pc.label, f"g{index}")
                        lane_budget = self.guard_budgets.setdefault(f"g{index}", GuardRetryBudget())
                        def factory(job, ident=model["id"], budget=lane_budget):
                            if job.get("model_id") != ident:
                                return FailedSource(job)
                            if runtime is not None and runtime.lane(ident) is not None:
                                def build():
                                    current = runtime.lane(ident)
                                    return LazyServerSource(job, current["url"], current["id"],
                                                            self.extra_checked, self.extra_checked_lock, budget)
                                return RuntimeSource(build, runtime, ident, job,
                                                     ready=lambda: self.guard_advertised_revision >= runtime.revision)
                            return LazyServerSource(job, getattr(self.args, "model_servers", {}).get(ident, self.args.server), ident,
                                                    self.extra_checked, self.extra_checked_lock, budget)

                        def lane_ready(ident=model["id"]):
                            if runtime is not None and ident in runtime.pending:
                                return False
                            lane = runtime.lane(ident) if runtime is not None else None
                            url = (lane["url"] if lane is not None else
                                   getattr(self.args, "model_servers", {}).get(ident, self.args.server))
                            return model_server_answers(url)

                        def lane_run(client=lane_pc, source_factory=factory, server_ready=lane_ready):
                            while not stop.is_set():
                                try:
                                    StandIn(client, source_factory, rate=1, emit=emit,
                                            show_text=False, give_up_after=30,
                                            server_ready=server_ready).run(stop)
                                except (OSError, ToolError, ValueError):
                                    self.events.put((generation, "A model stopped. Retrying."))
                                if not stop.is_set():
                                    client.epoch = None
                                    stop.wait(2)

                        lane = threading.Thread(target=lane_run, name=f"opos-gpu-g{index}", daemon=True)
                        lane.start()  # started before it is visible to tick(): an unstarted thread reads as dead
                        lane_threads.append(lane)
                    if self.generation == generation and not stop.is_set():
                        self.lane_workers = tuple(lane_threads)  # published whole, never half-built
                StandIn(pc, source, rate=1 if enabled else 4, emit=emit, show_text=False,
                        give_up_after=30, server_ready=main_ready).run(stop)
            except (OSError, ToolError, ValueError):
                self.events.put((generation, "Answer stopped. Checking the phone and model server."))
            finally:
                stop.set()
                if runtime is not None:
                    runtime.unlisten(runtime_event)
                pc.on_new_epoch = None
                join_within(lane_threads, LANE_JOIN_BUDGET)
                self.events.put((generation, "Reconnecting if the phone is ready."))

        self.worker_stop = stop
        worker = threading.Thread(target=run, name="opos-gpu-worker", daemon=True)
        self.worker = worker
        worker.start()
        if not self.running:
            stop.set()
            worker.join(6)
            if self.worker is worker and not worker.is_alive():
                self.worker = None
                self.worker_stop = None

    def _connect(self) -> None:
        if self.session_pc is not None and self.bridge.forward_present():
            if not model_server_listening(self.args.server):
                raise RetryLater("Error: Model server unavailable. Start it; GPU Link will retry.")
            self._start_preflight()
            return
        self.session_pc = None
        port = self.bridge.create_forward()
        if not self.running:
            self.bridge.remove_own_forward()
            return
        launch_failed = False

        def open_models_screen() -> bool:
            # Only after the phone service answered. Opening the app while the backend is
            # down (for example after a USB replug killed it) would steal the screen every
            # retry. Also rate limited so a failing preflight cannot make it flicker.
            if self.args.no_launch:
                return False
            now = self.clock()
            if now - getattr(self, "last_launch", -1e9) < 60:
                return False
            self.last_launch = now
            try:
                self.bridge.launch_models()
            except RetryLater:
                return True  # The notification can still open the models screen.
            return False

        if not self.running:
            self.bridge.remove_own_forward()
            return
        key = self.keys.load()
        if key is None:
            if self.pending_key is None:
                self.pending_key = secrets.token_bytes(proto.KEY_BYTES)
            key = self.pending_key
            pc = PC(f"127.0.0.1:{port}", key, self.args.label)
            pc.hello()  # Verify the app service before asking for PC permission.
            launch_failed = open_models_screen()
            self.ensure_permission()
            if not self.running:
                self.bridge.remove_own_forward()
                return
            if not authenticated_idle(pc):
                status, state = self.bridge.enrol(pc)
                if status != 202 or state != "pending":
                    if status == 403 and state == "closed":
                        raise CompanionError("Error: Pairing is closed. Tap Allow pairing again on the phone.")
                    if status == 409 and state == "enrolled":
                        raise CompanionError("Error: Phone is already paired. Use Forget on the phone, then retry.")
                    raise CompanionError("Error: Phone did not accept pairing. Check the phone, then retry.")
                approved = self.wait_for_phone_allow(pc)
                if not self.running:
                    self.bridge.remove_own_forward()
                    return
                if not approved:
                    raise CompanionError("Error: Pairing was not allowed on the phone. Replug to try again.")
            if not self.running:
                self.bridge.remove_own_forward()
                return
            self.keys.save_first_allow(key)
            self.pending_key = None
        else:
            pc = PC(f"127.0.0.1:{port}", key, self.args.label)
            if not self.running:
                self.bridge.remove_own_forward()
                return
            if not authenticated_idle(pc):
                raise CompanionError("Error: Saved pairing was rejected. Tap Forget on the phone, then restart GPU Link with pairing reset for this phone.")
            launch_failed = open_models_screen()
            self.ensure_permission()
        if not self.link_present():
            raise RetryLater("USB link lost during pairing. Replug to retry.")
        self.session_pc = pc
        self.session_launch_failed = launch_failed
        if not model_server_listening(self.args.server):
            raise RetryLater("Error: Model server unavailable. Start it; GPU Link will retry.")
        self._start_preflight()

    def _start_preflight(self) -> None:
        if self.preflight_thread is not None:
            return  # One in-flight request per attachment session.
        cancel = threading.Event()
        done = threading.Event()
        self.preflight_cancel, self.preflight_done = cancel, done
        self.preflight_result = False
        self.status.set("Checking the model.")

        def run():
            try:
                self.preflight_result = model_server_preflight(
                    self.args.server, self.args.model, cancelled=cancel.is_set)
            except (OSError, ValueError, TypeError, ToolError):
                self.preflight_result = False
            finally:
                done.set()
                self.wake.set()

        self.preflight_thread = threading.Thread(target=run, name="opos-model-preflight", daemon=True)
        self.preflight_thread.start()

    def _cancel_preflight(self) -> None:
        if getattr(self, "preflight_cancel", None) is not None:
            self.preflight_cancel.set()

    def _link_lost_while_warming(self) -> None:
        """Drop a session whose USB forward vanished before it came online.

        The first loss reconnects in 1 s, so a single blip feels instant. A forward
        that keeps vanishing backs off like any other failed attempt (3/6/10 s)
        instead of recreating it every second.
        """
        self.session_pc = None
        self.bridge.remove_own_forward()
        self.status.set("USB link lost. Reconnecting.")
        losses = getattr(self, "preflight_link_losses", 0) + 1
        self.preflight_link_losses = losses
        if losses == 1:
            self.next_try = self.clock() + 1
            self.retry_delay = 3
        else:
            self._schedule_retry()

    def _schedule_retry(self) -> None:
        self.next_try = self.clock() + self.retry_delay
        self.retry_delay = min(10, self.retry_delay * 2)  # a replug must feel instant

    def _finish_preflight(self, present: bool) -> None:
        if self.preflight_thread is None or self.preflight_done is None or not self.preflight_done.is_set():
            return
        self.preflight_thread.join(0)
        success = self.preflight_result and not self.preflight_cancel.is_set()
        self.preflight_thread = None
        self.preflight_done = None
        self.preflight_cancel = None
        if not present or not self.running or self.session_pc is None:
            return
        if success and self.bridge.forward_present():
            self._start_worker(self.session_pc)
            if self.running:
                self.online = True
                self.detached_at = None
                self.retry_delay = 3
                self.preflight_link_losses = 0
                self.status.set("Ready for questions on the phone."
                                if not self.session_launch_failed else
                                "Ready. Open GPU Link from the phone notification.")
            return
        if not self.bridge.forward_present():
            # The forward disappeared while the one-token check ran, whether it
            # returned true or false. Blame the link, not the model route.
            self._link_lost_while_warming()
            return
        self.preflight_link_losses = 0  # only consecutive link losses back off
        self.status.set("Error: Model check failed. Check the model server and selected model; retrying.")
        self._schedule_retry()

    def tick(self) -> None:
        if not self.running:
            return
        refresh = getattr(self, "guard_refresh", None)
        if refresh is not None and refresh.is_set():
            refresh.clear()
            try:
                if not self.guard_advertise():
                    raise ToolError("extra model advertisement refused")
            except (OSError, ToolError, ValueError):
                if self.worker_stop is not None:
                    self.worker_stop.set()
        while not self.events.empty():
            event = self.events.get_nowait()
            if isinstance(event, tuple):
                generation, line = event
                if generation == getattr(self, "generation", 0):
                    self.status.set(line)
            else:
                self.status.set(event)
        try:
            now = self.clock()
            if (self.granted and not getattr(self.args, "always_allow", False)
                    and self.detached_at is not None and now - self.detached_at >= 120):
                self.granted = False
            present = self.bridge.authorized()
            if present:
                self.detached_at = None
            else:
                self.last_launch = -1e9  # a real replug may open the models screen again
                self._cancel_preflight()
                self.session_pc = None
                self.bridge.remove_own_forward()
                # Also cover the warming window, when self.online is still False.
                self.preflight_link_losses = 0  # a replug must feel instant again
                self.status.set("Phone paused. Replug or allow USB access to resume.")
                self.next_try = self.clock() + 1
                self.retry_delay = 3
            if (present and not self.online and self.preflight_thread is not None
                    and self.preflight_cancel is not None and not self.preflight_cancel.is_set()
                    and not self.bridge.forward_present()):
                # Lost USB forward during warmup (phone still listed). Run once
                # per interruption so later ticks do not keep postponing next_try.
                self._cancel_preflight()
                self._link_lost_while_warming()
            forward_ok = present and self.bridge.forward_present() if self.online else False
            server_ok = model_server_listening(self.args.server) if forward_ok else False
            worker_ok = self._workers_alive()
            if self.online and not (present and forward_ok and server_ok and worker_ok):
                self._stop_worker()
                self._cancel_preflight()
                self.bridge.remove_own_forward()
                self.session_pc = None
                self.online = False
                self.detached_at = self.clock() if not present else None
                if not present:
                    self.status.set("Phone paused. Replug or allow USB access to resume.")
                elif not forward_ok:
                    self.status.set("USB link lost. Reconnecting.")
                elif not server_ok:
                    self.status.set("Error: Model server unavailable. Start it; GPU Link will retry.")
                else:
                    self.status.set("Answer stopped. Retrying.")
                self.next_try = self.clock() + 2
                self.retry_delay = 3
            self._finish_preflight(present)
            if not present:
                if self.granted and self.detached_at is None:
                    self.detached_at = self.clock()
                self.blocked_until_detach = False
            elif (not self.online and self.preflight_thread is None
                  and self.clock() >= self.next_try and not self.blocked_until_detach):
                if self.worker is not None and (self.worker.is_alive() or any(
                    lane.is_alive() for lane in getattr(self, "lane_workers", []))):
                    self.status.set("Waiting for the previous answer to stop.")
                else:
                    self._connect()
        except GrantDeclined as error:
            self._stop_worker()
            self.bridge.remove_own_forward()
            self.status.set(str(error))
            self.blocked_until_detach = True
        except RetryLater as error:
            self._stop_worker()
            if self.session_pc is None:
                self.bridge.remove_own_forward()
            self.status.set(str(error))
            self._schedule_retry()
        except CompanionError as error:
            self._stop_worker()
            self._cancel_preflight()
            self.bridge.remove_own_forward()
            self.session_pc = None
            self.status.set(presenter_error(error))
            self.blocked_until_detach = True
        except (OSError, ToolError, ValueError):
            self._stop_worker()
            self._cancel_preflight()
            self.bridge.remove_own_forward()
            self.session_pc = None
            self.status.set("Error: Phone service unavailable. Check the phone; retrying.")
            self._schedule_retry()
        if not getattr(self, "headless", False):
            self._refresh_main_window()
            self.root.after(1000, self.tick)

    def _refresh_main_window(self) -> None:
        if not hasattr(self, "main_window"):
            return
        link_words, link_ink, status_ink = _main_window_tone(
            self.online, self.status.get())
        self.main_window["link_state"].set(link_words)
        self.main_window["link_label"].configure(fg=link_ink)
        self.main_window["status_label"].configure(fg=status_ink)

    def retry(self) -> None:
        """A deliberate retry after the owner clears the phone's lockout."""
        self.blocked_until_detach = False
        self.next_try = 0
        self.retry_delay = 3
        self.status.set("Checking the phone again.")

    def remove_model_copies(self) -> None:
        """Remove marked cache downloads after the owner confirms the path."""
        from gpu_link_autosetup import model_cache_is_inside_data_dir, remove_model_copies

        models_dir = self.args.models_dir
        if not model_cache_is_inside_data_dir(self.args.data_dir, models_dir):
            message = "Model copies were not removed: the cache is not inside the companion data directory"
            self.status.set(message)
            print("GPU Link: " + message, flush=True)
            return
        if not _confirm_remove_model_copies(self.root, models_dir, self.tk):
            return
        try:
            removed = remove_model_copies(self.args.data_dir, models_dir)
        except (OSError, RuntimeError, ValueError) as error:
            message = str(error) or "Model copies could not be removed from the companion cache"
            self.status.set(message)
            print("GPU Link: " + message, flush=True)
            return
        if removed == 0:
            message = f"No GPU Link-marked copies found in {models_dir}"
        else:
            file_word = "file" if removed == 1 else "files"
            message = f"Removed model copies from {models_dir} ({removed} {file_word})"
        self.status.set(message)
        print("GPU Link: " + message, flush=True)

    def stop(self) -> None:
        self.running = False
        if hasattr(self, "wake"):
            self.wake.set()
        self._cancel_preflight()
        if self.preflight_thread is not None:
            self.preflight_thread.join(2)
        self._stop_worker()
        self.bridge.remove_own_forward()
        self.session_pc = None
        self.cleanup_ok = self._cleanup_done()
        self.status.set("Stopped." if self.cleanup_ok else
                        "Error: Stop was incomplete. Check the USB link and model server.")
        if not self.headless:
            self.root.destroy()

    def _cleanup_done(self) -> bool:
        return ((self.worker is None or not self.worker.is_alive())
                and not any(lane.is_alive() for lane in getattr(self, "lane_workers", []))
                and (self.preflight_thread is None or not self.preflight_thread.is_alive())
                and self.bridge.port is None and self.bridge.provisional_port is None)

    def run(self) -> None:
        try:
            if self.headless:
                while self.running:
                    self.tick()
                    self.wake.wait(1)
                    self.wake.clear()
            else:
                self.root.after(0, self.tick)
                self.root.mainloop()
        finally:
            self._cancel_preflight()
            if self.preflight_thread is not None:
                self.preflight_thread.join(2)
            self._stop_worker()
            self.bridge.remove_own_forward()
            self.cleanup_ok = self._cleanup_done()
            if self.headless and not self.running:
                self.status.set("Stopped." if self.cleanup_ok else
                                "Error: Stop was incomplete. Check the USB link and model server.")


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n", 1)[0] or None)
    parser.add_argument("--serial", help="authorized USB adb device serial; auto-select if exactly one")
    parser.add_argument("--adb", default="adb", help="adb executable from Android platform tools")
    parser.add_argument("--label", help="pairing label sent to the phone (1 to 24 letters, digits, spaces or hyphens); "
                        "the phone keeps the label it saw at pairing, so a new one takes effect only "
                        "after Forget on the phone and --reset-pairing here")
    routes = parser.add_mutually_exclusive_group()
    routes.add_argument("--server", help="local model server chat URL")
    routes.add_argument("--lm-url", help="local model server address or chat URL")
    parser.add_argument("--discover", action="store_true", help="list local model servers and exit")
    parser.add_argument("--probe-url", action="append", default=[], help="also check this local model server address")
    parser.add_argument("--allow-protected-port", action="store_true",
                        help="permit protected ports only for exact --probe-url entries")
    parser.add_argument("--json", action="store_true", help="emit machine-readable discovery results")
    parser.add_argument("--model", default=os.environ.get("OPOS_GPU_LINK_MODEL"),
                        help="model name at that local server (or OPOS_GPU_LINK_MODEL)")
    extra = parser.add_mutually_exclusive_group()
    extra.add_argument("--extra-model", action="append", default=[], metavar="ID:LABEL:MAKER",
                       help="another computer model, repeat up to three times")
    extra.add_argument("--models-file", type=Path, metavar="JSON",
                       help="JSON object with an ordered models array (up to three)")
    parser.add_argument("--model-server", action="append", default=[], metavar="ID=URL",
                        help="local chat URL for an extra model ID")
    parser.add_argument("--key-dir", type=Path, default=None, help="per-user pairing directory")
    parser.add_argument("--headless", action="store_true", help="print status in the terminal without a window")
    parser.add_argument("--always-allow", action="store_true",
                        help="remember this computer's permission for this phone while the companion runs")
    parser.add_argument("--no-launch", action="store_true", help="do not bring the models UI forward")
    parser.add_argument("--reset-pairing", action="store_true",
                        help="while stopped, remove only --serial's saved key; never contacts adb")
    args = parser.parse_args(argv)
    if args.json and not args.discover:
        parser.error("--json requires --discover")
    if args.discover:
        return args
    if args.label is None:
        args.label = f"OPOS GPU {computer_noun()}"
    if args.serial is not None and not valid_usb_serial(args.serial):
        parser.error("serial must be a USB adb serial, not a network or emulator transport")
    if not proto.valid_label(args.label):
        parser.error("label must contain 1 to 24 letters, digits, spaces or hyphens")
    explicit_url = args.lm_url if args.lm_url is not None else args.server
    try:
        if args.lm_url is not None:
            args.server = gpu_link_discover.chat_url(args.lm_url)
        elif args.server is None:
            args.server = DEFAULT_SERVER
        _, port, _ = endpoint(args.server)
    except (ValueError, ToolError):
        parser.error("endpoint must name a loopback host and a valid port")
    if not gpu_link_discover.protected_allowed(
        explicit_url, port, args.probe_url, args.allow_protected_port,
    ):
        parser.error("protected backend port requires the exact URL in --probe-url and --allow-protected-port")
    args.auto_discover = explicit_url is None
    if args.reset_pairing and args.serial is None:
        parser.error("--reset-pairing requires an explicit --serial")
    if not args.reset_pairing and (not args.model or len(args.model) > 128):
        parser.error("set --model or OPOS_GPU_LINK_MODEL (1 to 128 characters)")
    try:
        if args.models_file is not None:
            with args.models_file.open("rb") as handle:
                raw = handle.read(proto.STATUS_BODY_LIMIT + 1)
            config = proto.loads(raw, proto.STATUS_BODY_LIMIT)
            if set(config) != {"models"} or not isinstance(config["models"], list):
                raise ValueError
            models = []
            for row in config["models"]:
                if not isinstance(row, dict) or not {"id", "label", "maker"} <= set(row) <= {"id", "label", "maker", "gpu"}:
                    raise ValueError
                models.append({**row, "gpu": row.get("gpu")})
        else:
            models = []
            for value in args.extra_model:
                fields = value.split(":", 2)
                if len(fields) != 3:
                    raise ValueError
                models.append(dict(zip(("id", "label", "maker"), fields), gpu=None))
        args.extra_models = proto.parse_advertise(proto.dumps({"models": models}))
        if any(model["id"] == args.model for model in args.extra_models):
            raise ValueError("extra model duplicates main")
    except (OSError, ValueError, proto.ProtoError):
        parser.error("extra models need up to 3 unique ID:LABEL:MAKER entries or a bounded models JSON file")
    args.model_servers = {}
    for value in args.model_server:
        ident, sep, url = value.partition("=")
        try:
            if not sep or not proto.valid_model_id(ident):
                raise ValueError
            _, mport, _ = endpoint(url)
            if mport in FORBIDDEN_PC_PORTS and not args.allow_protected_port:
                raise ValueError
        except (ValueError, ToolError):
            parser.error("--model-server needs ID=loopback chat URL on an unprotected port")
        args.model_servers[ident] = url
    if args.key_dir is None:
        base = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
        args.key_dir = Path(base) / "OPOS" / "GPU Link" if base else Path.home() / ".config" / "opos-gpu-link"
    return args


def resolve_launch_adb(adb: str, runner=subprocess.run, system=None) -> str:
    """Use the running adb server's executable when one is already listening.

    Direct entry points (opos_gpu_link.py, run-mac.sh, run-linux.sh,
    run-windows.ps1) used to pass --adb through unchanged, so a PATH or
    Homebrew binary could fail the forward owner check. Detection lives in
    gpu_link_autosetup so the launcher and these entry points share it.
    """
    try:
        import gpu_link_autosetup as setup
    except ImportError as error:
        bare = adb == Path(adb).name and not adb.startswith(".")
        if bare:
            found = shutil.which(adb)
            if found:
                try:
                    return str(Path(found).resolve())
                except OSError:
                    return found
        else:
            path = Path(adb)
            if path.is_file():
                try:
                    return str(path.resolve())
                except OSError:
                    return str(path.absolute())
        raise CompanionError("adb is unavailable; install or select Android platform tools") from error
    try:
        return str(setup.ensure_adb(Path("."), explicit=adb, allow_download=False,
                                    runner=runner, system=system))
    except RuntimeError as error:
        raise CompanionError(str(error)) from error


def main(argv=None, runtime=None, data_dir=None, models_dir=None) -> int:
    args = arguments(argv)
    args.runtime = runtime
    if data_dir is None:
        from gpu_link_autosetup import data_dir as companion_data_dir
        data_dir = companion_data_dir()
    args.data_dir = Path(data_dir)
    args.models_dir = Path(models_dir) if models_dir is not None else args.data_dir / "models"
    if args.discover:
        gpu_link_discover.print_discovery(args.probe_url, args.allow_protected_port, args.json)
        return 0
    if args.reset_pairing:
        try:
            guard = InstanceGuard(args.key_dir, args.serial)
        except (OSError, CompanionError) as error:
            print("GPU Link: " + presenter_error(error), file=sys.stderr)
            return 2
        try:
            removed = KeyStore(args.key_dir, args.serial).reset()
            print("GPU Link: " + ("Saved pairing removed for this serial" if removed
                                  else "No saved pairing for this serial"), flush=True)
            return 0
        except CompanionError as error:
            print("GPU Link: " + presenter_error(error), file=sys.stderr)
            return 2
        finally:
            guard.close()
    computer_noun()  # one short local query now, never on the Tk thread or a worker later
    if args.auto_discover:
        backends = gpu_link_discover.discover(args.probe_url, args.allow_protected_port)
        if len(backends) == 1:
            url = backends[0]["url"]
            _, _, port, _ = gpu_link_discover.probe_origin(url)
            if port not in gpu_link_discover.PROTECTED_PORTS:
                args.server = gpu_link_discover.chat_url(url)
                print("GPU Link: Using discovered backend " + args.server, flush=True)
            else:
                print("GPU Link: Skipping automatic selection of protected backend " + url, flush=True)
    try:
        args.adb = resolve_launch_adb(args.adb)
    except CompanionError as error:
        print("GPU Link: " + presenter_error(error), file=sys.stderr)
        return 2
    if args.serial is None:
        try:
            args.serial = select_serial(args.adb)
            if args.serial is None:
                print("GPU Link: Waiting for exactly one authorized USB phone", flush=True)
            while args.serial is None:
                time.sleep(2)
                args.serial = select_serial(args.adb)
        except KeyboardInterrupt:
            print("GPU Link: Stopped while waiting for a USB phone", flush=True)
            return 130
        except CompanionError as error:
            print("GPU Link: " + presenter_error(error), file=sys.stderr)
            return 2
    try:
        guard = InstanceGuard(args.key_dir, args.serial)
    except (OSError, CompanionError) as error:
        print("GPU Link: " + presenter_error(error), file=sys.stderr)
        return 2
    try:
        root, tk = None, None
        headless = args.headless
        if not headless:
            try:
                import tkinter as tk
                root = tk.Tk()
                root.title("OPOS GPU Link")
            except (ImportError, RuntimeError):
                headless = True
            except Exception as error:
                if tk is not None and isinstance(error, tk.TclError):
                    headless = True
                else:
                    raise
        app = Companion(args, root, tk, headless=headless)
        old_handlers = {}
        if headless:
            for sig in (signal.SIGINT, signal.SIGTERM):
                old_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, lambda _signum, _frame: app.stop())
        try:
            app.run()
        finally:
            for sig, previous in old_handlers.items():
                signal.signal(sig, previous)
        return 0 if app.cleanup_ok else 3
    finally:
        guard.close()


if __name__ == "__main__":
    raise SystemExit(main())

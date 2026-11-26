# SPDX-License-Identifier: Apache-2.0
"""Plug-and-play setup for the OPOS GPU Link desktop companion.

Run once on any computer: it finds this computer's GPU, an inference runtime
and models that fit, finds (or fetches) adb, waits for the phone with clear
instructions, then starts the signed GPU Link companion against the local
models. No relays: the phone talks only to this computer, over USB.

Safety rules baked in:
- Only loopback servers are probed, and only GET /v1/models.
- Protected ports are never probed unless the listener belongs to LM Studio
  (checked by process *name* only; command lines are never read, because they
  can contain API keys). --strict-ports skips them entirely.
- Servers that need an API key are skipped; no key of yours is read or sent.
- Our own llama-server instances bind 127.0.0.1 only, require a random per-run
  key (given via a private temp file that is deleted once the servers are up,
  and via an environment variable of this process for the companion; never on
  a command line, in a log or on screen), and accept same-origin CORS only.
- Every download is checked against a pinned SHA-256 before it is used.
- A model is loaded only when we launch our own server, and every server is
  stopped (models unloaded) when the companion exits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))
HERE = Path(__file__).resolve().parent
RESOURCES = Path(getattr(sys, "_MEIPASS", HERE))  # where PyInstaller unpacks bundled files
sys.path.insert(0, str(HERE))
import gpu_link_discover  # noqa: E402
import gpu_link_pins as pins  # noqa: E402

try:
    from gpu_link_health import FallbackPlan, Model, Watchdog, PROTECTED_PORTS, PROTECTED_PIDS, watchdog_enabled
except ImportError:
    FallbackPlan = Model = Watchdog = None
    PROTECTED_PORTS = frozenset()
    PROTECTED_PIDS = frozenset({41484, 10188, 24001})


# We never *launch* on a protected port, nor on 1235 (LM Studio's usual port).
LAUNCH_FORBIDDEN = frozenset(gpu_link_discover.PROTECTED_PORTS) | {1235, 1237, 41484, 56795, 56740, 24001}
CANDIDATE_PORTS = (1235, 8000, 8001, 5001, 1337, 18090, 18091, 18092, 18093)
LMSTUDIO_DEFAULT_PORT = 1234
DEFAULT_LAUNCH_PORT = 18090
LLAMA_TAG = pins.LLAMA_TAG
GITHUB_RELEASE = "https://github.com/ggml-org/llama.cpp/releases/download/{tag}/{name}"
KEY_ENV = "OPOS_GPU_LINK_SERVER_KEY"
OFFLINE_ENV = "OPOS_GPU_LINK_OFFLINE"  # 1/true/yes/on: refuse downloads (show-day / --offline)
GPU_ENV = "OPOS_GPU_LINK_GPU"  # auto | nvidia | amd | intel | cpu: which GPU vendor to use (hides the others)
GPU_CHOICES = ("auto", "nvidia", "amd", "intel", "cpu")
FAKE_DRIVER_ENV = "OPOS_GPU_LINK_FAKE_NVIDIA_DRIVER"  # test hook: pretend nvidia-smi reported this driver version
MIN_MEASURED_VRAM_MB = 2048  # a GPU with less dedicated memory (an iGPU) keeps the fixed Vulkan budget
ALIAS = "opos-gpu-link"
CTX = 8192
VRAM_MARGIN_MB = 512  # reserved from free VRAM; 768 left the 5080 107 MB short of 3 lanes, see test
CPU_BUDGET_MB = 2000
IGPU_BUDGET_CAP_MB = 3500
SLOTS = 2
MAX_EXTRAS = 2
# A demo wants snappy answers: by default cap the main model's file size even
# when more memory is free (OPOS_GPU_LINK_MAX_MODEL_MB or --budget-mb changes it).
DEMO_MAX_MB = int(os.environ.get("OPOS_GPU_LINK_MAX_MODEL_MB", "10000"))

# NVIDIA first: "Llama-3.1-Nemotron" and "Nemotron-3.5-Bolt" (post-trained from Gemma 4) are NVIDIA models.
MAKERS = (("nemotron", "NVIDIA"), ("aceinstruct", "NVIDIA"), ("minitron", "NVIDIA"),
          ("gemma", "Google"), ("qwen", "Qwen"), ("llama", "Meta"), ("mistral", "Mistral AI"),
          ("phi", "Microsoft"), ("lfm", "Liquid AI"), ("smollm", "Hugging Face"),
          ("granite", "IBM"), ("deepseek", "DeepSeek"), ("glm", "Z.ai"))
SKIP_GGUF = re.compile(r"(mmproj|embed|rerank|vocab|clip|whisper|-0000[2-9]-of-|dflash|draft|eagle|speculat)", re.I)
# Coder / math / tool-tuned models are poor demo answerers for general questions.
CODER = re.compile(r"(coder|codestral|codegemma|codellama|starcoder|devstral|[-_.]code[-_.]|math|prover)", re.I)


def say(message: str) -> None:
    print("GPU Link: " + message, flush=True)


def banner(lines) -> None:
    width = max(len(line) for line in lines) + 4
    print("\n" + "=" * width, flush=True)
    for line in lines:
        print("  " + line, flush=True)
    print("=" * width + "\n", flush=True)


def _run(cmd, runner=subprocess.run, timeout=10, env=None):
    try:
        result = runner(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        timeout=timeout, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8", "replace")


def data_dir() -> Path:
    """Where downloads and logs live. Next to the script when run from source;
    in the user's data folder for a bundle (its own folder is temporary)."""
    env = os.environ.get("OPOS_GPU_LINK_HOME")
    if env:
        return Path(env)
    if not FROZEN:
        return HERE
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Application Support" / "OPOS GPU Link"
    if system == "Windows":
        return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "OPOS" / "GPU Link"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "opos-gpu-link"


# ---------------------------------------------------------------- GPU ----

def cpu_has_avx(runner=subprocess.run, system=None) -> bool:
    system = system or platform.system()
    if platform.machine().lower() in ("arm64", "aarch64"):
        return True  # AVX is an x86 feature; Arm builds do not need it
    if system == "Linux":
        try:
            return " avx " in " " + Path("/proc/cpuinfo").read_text().split("flags", 1)[1].split("\n", 1)[0] + " "
        except (OSError, IndexError):
            return True
    if system == "Darwin":
        feats = (_run(["sysctl", "-n", "machdep.cpu.features"], runner) or "") + \
                (_run(["sysctl", "-n", "machdep.cpu.leaf7_features"], runner) or "")
        return "AVX1.0" in feats or "AVX2" in feats
    return True


VENDOR_IDS = {0x10DE: "NVIDIA", 0x1002: "AMD", 0x8086: "Intel"}
NVIDIA_NAME = re.compile(r"\b(?:NVIDIA|GeForce|Quadro|Tesla)\b|\b(?:RTX|GTX)(?=\b|\d)", re.I)
NVIDIA_ICD = re.compile(r"nvidia|nouveau", re.I)
CUDA_DEVICE = re.compile(r"^\s*CUDA\d*\s*:", re.I)
SOFTWARE_GPU = re.compile(r"\b(?:llvmpipe|lavapipe|software|swrast)\b", re.I)
VIRTUAL_GPU = re.compile(r"\b(?:VMware|QEMU|virtio|Red Hat|Microsoft Hyper-V|ASPEED|Matrox)\b", re.I)
VENDOR_NAMES = {
    "NVIDIA": NVIDIA_NAME,
    "AMD": re.compile(r"Advanced Micro Devices|\[AMD/ATI\]|\b(?:AMD|ATI|Radeon)\b", re.I),
    "Intel": re.compile(r"\b(?:Intel|Arc)\b", re.I),
}
DISCRETE_NAMES = {
    "AMD": re.compile(r"\b(?:Radeon (?:RX|Pro|VII)\b|Radeon (?:R9|R7|HD)\b|Instinct|FirePro\b)", re.I),
    "Intel": re.compile(r"\b(?:Arc|DG1|DG2|Battlemage|BMG|Data Center GPU)\b", re.I),
}
PCI_SLOT = re.compile(r"[\da-f]{4}:[\da-f]{2}:[\da-f]{2}\.[0-7]", re.I)
PCI_GPU = re.compile(
    r"^\s*((?:[\da-f]{4}:)?[\da-f]{2}:[\da-f]{2}\.[0-7])\s+"
    r"(?:VGA|3D|Display)\b[^:]*:\s*(.+)$", re.I)
DRM_ROOT = Path("/sys/class/drm")


def hide_nvidia(environ=None) -> bool:
    environ = os.environ if environ is None else environ
    return (environ.get("OPOS_GPU_LINK_HIDE_NVIDIA", "").strip().lower() in ("1", "true", "yes", "on")
            or environ.get("CUDA_VISIBLE_DEVICES", "0").strip() in ("", "-1", "NoDevFiles"))


def env_flag(value) -> bool:
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def is_offline(environ=None) -> bool:
    """True when --offline (or $OPOS_GPU_LINK_OFFLINE) has turned downloads off."""
    environ = os.environ if environ is None else environ
    return env_flag(environ.get(OFFLINE_ENV))


def user_opted_out_of_offline_default(user_argv):
    """True when the user already chose a fetch or download policy flag."""
    argv = [str(a) for a in user_argv]
    return any(a in ("--prefetch", "--offline", "--no-download") for a in argv)


def start_script_argv(user_argv):
    """Flags show-day start scripts prepend. --prefetch stays the at-home fetch path."""
    if user_opted_out_of_offline_default(user_argv):
        return []
    return ["--offline"]


def should_default_offline(user_argv, frozen=None):
    """Frozen one-file apps default to --offline, same contract as the start scripts."""
    if frozen is None:
        frozen = FROZEN
    if not frozen:
        return False
    return not user_opted_out_of_offline_default(user_argv)



def describe_gpu(name):
    """Classify a PCI or Windows display adapter by its reported name."""
    if VIRTUAL_GPU.search(name) or SOFTWARE_GPU.search(name):
        return None
    for vendor, pattern in VENDOR_NAMES.items():
        if pattern.search(name):
            return {"vendor": vendor, "name": name,
                    "discrete": vendor == "NVIDIA" or bool(DISCRETE_NAMES[vendor].search(name))}
    return None


def pci_gpus(text):
    for line in text.splitlines():
        match = PCI_GPU.match(line)
        if match:
            slot, name = match.groups()
            gpu = describe_gpu(re.sub(r"\s*\(rev [\da-f]+\)\s*$", "", name, flags=re.I).strip())
            if gpu:
                yield slot.lower(), gpu


def parse_lspci(text):
    return [gpu for _, gpu in pci_gpus(text)]


def read_int(path, base=10):
    try:
        return int(path.read_text().strip(), base)
    except (OSError, ValueError):
        return None


def read_drm_cards(drm_root=DRM_ROOT):
    """Read optional memory counters on primary DRM nodes in MiB."""
    cards = []
    try:
        entries = sorted(Path(drm_root).iterdir())
    except OSError:
        return cards
    for entry in entries:
        if not re.fullmatch(r"card[0-9]+", entry.name):
            continue
        device = entry / "device"
        vendor = VENDOR_IDS.get(read_int(device / "vendor", 16))
        if not vendor:
            continue
        try:
            slot = device.resolve().name.lower()
        except (OSError, RuntimeError):
            slot = None
        card = {"card": entry.name, "vendor": vendor, "slot": slot,
                "boot_vga": read_int(device / "boot_vga")}
        for kind in ("vram", "gtt"):
            for field in ("total", "used"):
                value = read_int(device / f"mem_info_{kind}_{field}")
                card[f"{kind}_{field}_mb"] = bytes_to_mb(value)
        cards.append(card)
    return cards


def bytes_to_mb(value):
    try:
        return max(0, int(value) // (1024 * 1024))
    except (TypeError, ValueError, OverflowError):
        return None


def parse_rocm_cards(text):
    try:
        data = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(data, dict):
        return {}
    cards = {}
    for card, fields in data.items():
        if re.fullmatch(r"card[0-9]+", card) and isinstance(fields, dict):
            total = bytes_to_mb(fields.get("VRAM Total Memory (B)"))
            if total is not None:
                cards[card] = {"total_mb": total, "used_mb": bytes_to_mb(fields.get("VRAM Total Used Memory (B)"))}
    return cards


def parse_rocm_smi(text):
    return list(parse_rocm_cards(text).values())


def parse_vulkaninfo_summary(text):
    """Parse physical device records with numeric vendor IDs and short device types."""
    devices = []
    for block in re.split(r"^\s*GPU[0-9]+\s*:", text, flags=re.M)[1:]:
        fields = dict(re.findall(r"^\s*(deviceName|deviceType|vendorID)\s*=\s*([^\r\n]+)", block, re.M))
        try:
            devices.append({"name": fields["deviceName"].strip(),
                            "type": fields["deviceType"].strip().removeprefix("PHYSICAL_DEVICE_TYPE_"),
                            "vendor_id": int(fields["vendorID"].strip(), 16)})
        except (KeyError, ValueError):
            continue
    return devices


def integrated_budget(gtt_mb):
    limits = [IGPU_BUDGET_CAP_MB]
    try:
        match = re.search(r"^MemAvailable:\s+(\d+)\s+kB", Path("/proc/meminfo").read_text(), re.M)
        if match:
            limits.append(int(match[1]) // 2048)
    except OSError:
        pass
    if gtt_mb is not None:
        limits.append(gtt_mb // 2)
    return max(0, min(limits))


def card_for_gpu(cards, gpu, slot, vendor_count):
    matching = [card for card in cards if card["vendor"] == gpu["vendor"]]
    if slot:
        slot = slot if slot.count(":") == 2 else "0000:" + slot
        found = next((card for card in matching if card["slot"] == slot), None)
        if found:
            return found
        matching = [card for card in matching if not PCI_SLOT.fullmatch(card["slot"] or "")]
    return matching[0] if len(matching) == vendor_count == 1 else {}


def detect_vulkan_gpu(system, runner, which, hidden, drm_root, environ, only="auto"):
    """The best non-NVIDIA (or, without nvidia-smi, any) GPU seen through lspci/sysfs/ROCm/Vulkan/Windows.

    `hidden` (--hide-nvidia) ignores NVIDIA cards and masks its Vulkan driver; `only` ("amd"/"intel") ignores
    NVIDIA cards without masking the driver, so a mixed PC can be tested on its AMD or Intel GPU."""
    if only == "nvidia":
        return _forced_unavailable("nvidia")
    drop_nvidia = hidden or only in ("amd", "intel")
    candidates = []
    cards = []
    if system == "Linux":
        # Older callers inject a runner that handles the bare lspci command.
        candidates = list(pci_gpus(_run([which("lspci") or "lspci"], runner) or ""))
        cards = read_drm_cards(DRM_ROOT if drm_root is None else drm_root)
    elif system == "Windows":
        names = _run([which("powershell") or "powershell", "-NoProfile", "-Command",
                      "(Get-CimInstance Win32_VideoController).Name"], runner) or ""
        candidates = [(None, gpu) for line in names.splitlines() if (gpu := describe_gpu(line.strip()))]

    candidates = [(slot, gpu) for slot, gpu in candidates if not (drop_nvidia and gpu["vendor"] == "NVIDIA")]
    vulkan = []
    tool = which("vulkaninfo")
    if tool:
        env = hide_nvidia_env(environ, system=system) if hidden else None
        for device in parse_vulkaninfo_summary(_run([tool, "--summary"], runner, env=env) or ""):
            vendor = VENDOR_IDS.get(device["vendor_id"])
            if (vendor and not (hidden and vendor == "NVIDIA")
                    and device["type"] in ("DISCRETE_GPU", "INTEGRATED_GPU")
                    and not SOFTWARE_GPU.search(device["name"]) and not VIRTUAL_GPU.search(device["name"])):
                vulkan.append({"vendor": vendor, "name": device["name"],
                               "discrete": vendor == "NVIDIA" or device["type"] == "DISCRETE_GPU"})
    if not candidates:
        candidates = [(None, gpu) for gpu in vulkan if not (drop_nvidia and gpu["vendor"] == "NVIDIA")]
    if only in ("amd", "intel"):
        candidates = [(slot, gpu) for slot, gpu in candidates if gpu["vendor"].lower() == only]
    windows_rows = windows_gpu_memory(runner) if system == "Windows" and candidates else []

    rocm_cards = {}
    if system == "Linux" and any(gpu["vendor"] == "AMD" for _, gpu in candidates):
        tool = which("rocm-smi")
        if tool:
            rocm_cards = parse_rocm_cards(_run([tool, "--showmeminfo", "vram", "--json"], runner) or "")

    results = []
    for slot, gpu in candidates:
        vendor = gpu["vendor"]
        vendor_count = sum(other["vendor"] == vendor for _, other in candidates)
        peers = [other for other in vulkan if other["vendor"] == vendor]
        # A unique vendor match can classify a differently named PCI device.
        classified = next((other for other in peers if other["name"].lower() in gpu["name"].lower()), None)
        if not classified and len(peers) == vendor_count == 1:
            classified = peers[0]
        integrated = not (classified or gpu)["discrete"]
        card = card_for_gpu(cards, gpu, slot, vendor_count)
        rocm = rocm_cards.get(card.get("card")) if vendor == "AMD" else None
        if (vendor == "AMD" and rocm is None and not card and vendor_count == len(rocm_cards) == 1
                and sum(card["vendor"] == "AMD" for card in cards) <= 1):
            rocm = next(iter(rocm_cards.values()))
        total, used = card.get("vram_total_mb"), card.get("vram_used_mb")
        source = "assumed"
        if total is not None or (integrated and card.get("gtt_total_mb") is not None):
            source = "sysfs"
        if rocm:
            if total is None:
                total, used = rocm["total_mb"], rocm["used_mb"]
                source = "rocm-smi"
            elif used is None and total == rocm["total_mb"]:
                used = rocm["used_mb"]
        if system == "Windows" and total is None:
            row = match_adapter(windows_rows, gpu["name"])
            if row and row["total_mb"] >= MIN_MEASURED_VRAM_MB and row.get("used_mb") is not None:
                total, used, source = row["total_mb"], row["used_mb"], row.get("source", "windows-gpu-counters")
        free = max(0, total - (used or 0)) if total is not None else None
        measured_windows = system == "Windows" and source == "windows-gpu-counters"
        budget = (integrated_budget(card.get("gtt_total_mb")) if integrated and not measured_windows else
                  3500 if free is None else max(0, free - VRAM_MARGIN_MB))
        if vendor == "NVIDIA":
            budget = 3500  # no nvidia-smi measurements for this path
        result = {"vendor": vendor, "name": gpu["name"], "total_mb": total, "free_mb": free,
                  "driver": "", "backend": "vulkan", "budget_mb": budget, "integrated": integrated,
                  "rocm": bool(rocm), "vram_source": source}
        if source != "assumed":
            result["memory_source"] = source
        if card:
            result["drm_card"] = card["card"]
        results.append(result)
    if only in ("amd", "intel"):
        results = [gpu for gpu in results if gpu["vendor"].lower() == only]
    if results:
        best = max(results, key=lambda gpu: (not gpu["integrated"], gpu["total_mb"] or 0))
        if best["vendor"] != "NVIDIA" and any(gpu["vendor"] == "NVIDIA" for gpu in results + vulkan):
            best["nvidia_present"] = True
        if only in ("amd", "intel"):
            best["forced"] = only
        return best
    if only != "auto":
        return _forced_unavailable(only)
    return {"vendor": "none", "name": "CPU only", "total_mb": None, "free_mb": None,
            "driver": "", "backend": "cpu", "budget_mb": CPU_BUDGET_MB}


def normalize_gpu_choice(value) -> str:
    value = (value or "auto").strip().lower()
    return value if value in GPU_CHOICES else "auto"


def fake_driver_version(environ=None):
    """Test hook: OPOS_GPU_LINK_FAKE_NVIDIA_DRIVER=551.61 makes detect_gpu behave as if that driver is installed.
    Only digits and dots are accepted; anything else is ignored. The real driver is never changed."""
    environ = os.environ if environ is None else environ
    value = (environ.get(FAKE_DRIVER_ENV) or "").strip()
    return value if re.fullmatch(r"\d{1,4}(\.\d{1,4}){0,2}", value) else None


def _vulkan_gpu(vendor, name, memory=None):
    """A Vulkan-backend GPU. `memory` is a measured {total_mb, used_mb} (Windows/Linux) or None.

    With a measured dedicated size the budget is the memory that is really free minus the usual margin, like
    NVIDIA. Without a measurement (or on an iGPU) the old fixed 3.5 GB is kept."""
    gpu = {"vendor": vendor, "name": name, "total_mb": None, "free_mb": None, "driver": "",
           "backend": "vulkan", "budget_mb": 3500}
    if memory and (memory.get("total_mb") or 0) >= MIN_MEASURED_VRAM_MB and memory.get("used_mb") is not None:
        free = max(0, memory["total_mb"] - memory["used_mb"])
        gpu.update(total_mb=memory["total_mb"], free_mb=free, budget_mb=max(0, free - VRAM_MARGIN_MB),
                   memory_source=memory.get("source", "measured"))
    return gpu


def _detect_mac(runner, machine, hidden=False):
    """Apple Silicon (Metal), an AMD/Intel GPU in an Intel Mac (Metal), or the CPU."""
    mem = _run(["sysctl", "-n", "hw.memsize"], runner)
    total_mb = int(mem.strip()) // (1024 * 1024) if mem and mem.strip().isdigit() else 8192
    brand = (_run(["sysctl", "-n", "machdep.cpu.brand_string"], runner) or "Mac").strip()
    if machine in ("arm64", "aarch64"):
        # Metal's default working-set limit is ~2/3 (<=36 GB) to 3/4 of RAM;
        # keep headroom for macOS and the apps already running.
        budget = int(total_mb * (0.60 if total_mb <= 36864 else 0.70)) - 1024
        return {"vendor": "Apple", "name": brand or "Apple GPU", "total_mb": total_mb,
                "free_mb": None, "driver": "", "backend": "metal", "budget_mb": max(0, budget)}
    sp = _run(["system_profiler", "SPDisplaysDataType"], runner, timeout=20) or ""
    if hidden:
        blocks = re.split(r"(?=^[ \t]*Chipset Model:)", sp, flags=re.M)
        sp = "".join(block for block in blocks if not NVIDIA_NAME.search(block.partition("\n")[0]))
    chip = re.search(r"Chipset Model:\s*(.+)", sp)
    vram = re.search(r"VRAM[^:]*:\s*(\d+)\s*(GB|MB)", sp)
    if chip and vram:
        vram_mb = int(vram.group(1)) * (1024 if vram.group(2) == "GB" else 1)
        name = chip.group(1).strip()
        if "AMD" in name or "Radeon" in name:
            return {"vendor": "AMD", "name": name, "total_mb": vram_mb, "free_mb": None, "driver": "",
                    "backend": "metal", "budget_mb": max(0, vram_mb - 1500), "cpu": brand}
        # An Intel iGPU (about 1.5 GB of shared memory) or an old NVIDIA card: no Metal path of ours has been
        # verified on them, and the VRAM budget would be ~0, so answer on the CPU like any computer without a GPU.
        return {"vendor": "Intel Mac GPU", "name": name, "total_mb": vram_mb, "free_mb": None, "driver": "",
                "backend": "cpu", "budget_mb": CPU_BUDGET_MB, "cpu": brand,
                "note": f"{name}: GPU Link has not verified this GPU on a Mac; using the CPU"}
    return {"vendor": "Intel Mac", "name": brand, "total_mb": total_mb, "free_mb": None,
            "driver": "", "backend": "cpu", "budget_mb": max(0, total_mb // 3)}


def _forced_unavailable(only):
    """A vendor was requested with --gpu but this computer has none: use the CPU rather than another GPU."""
    label = {"amd": "AMD", "intel": "Intel", "nvidia": "NVIDIA"}.get(only, only)
    return {"vendor": "none", "name": f"CPU only (no {label} GPU found)", "total_mb": None, "free_mb": None,
            "driver": "", "backend": "cpu", "budget_mb": 2000, "forced": only}




def detect_gpu(runner=subprocess.run, system=None, machine=None, which=shutil.which, only=None, environ=None,
               drm_root=None):
    """Return {vendor, name, total_mb, free_mb, driver, backend, budget_mb}.

    `only` (or OPOS_GPU_LINK_GPU / --gpu) restricts detection to one vendor: "amd" and "intel" ignore a
    present NVIDIA card (so the Vulkan path can be used and tested on a mixed PC), "nvidia" ignores the
    others, "cpu" uses no GPU. "auto" prefers NVIDIA, then Apple/AMD/Intel as before.

    --hide-nvidia (OPOS_GPU_LINK_HIDE_NVIDIA, or CUDA_VISIBLE_DEVICES="") is separate: it pretends there is no
    NVIDIA card at all (nvidia-smi, PCI, Vulkan driver) and works together with `only`."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    environ = os.environ if environ is None else environ
    only = normalize_gpu_choice(only if only is not None else environ.get(GPU_ENV))
    hidden = hide_nvidia(environ)
    visibility = {"nvidia_hidden": True} if hidden else {}
    if only == "cpu":
        return {"vendor": "none", "name": "CPU only (forced)", "total_mb": None, "free_mb": None,
                "driver": "", "backend": "cpu", "budget_mb": CPU_BUDGET_MB, "forced": "cpu", **visibility}
    smi = which("nvidia-smi") if only in ("auto", "nvidia") and system != "Darwin" and not hidden else None
    if smi is None and system == "Windows" and only in ("auto", "nvidia") and not hidden:
        candidate = Path(environ.get("SystemRoot") or os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "nvidia-smi.exe"
        smi = str(candidate) if candidate.exists() else None
    if smi:
        out = _run([smi, "--query-gpu=name,memory.total,memory.free,driver_version",
                    "--format=csv,noheader,nounits"], runner)
        rows = [r for r in (out or "").splitlines() if r.count(",") >= 3]
        best = None
        for row in rows:
            name, total, free, driver = [f.strip() for f in row.split(",")[:4]]
            try:
                total_mb, free_mb = int(float(total)), int(float(free))
            except (ValueError, OverflowError):
                continue
            if best is None or free_mb > best["free_mb"]:
                best = {"vendor": "NVIDIA", "name": name, "total_mb": total_mb,
                        "free_mb": free_mb, "driver": driver, "backend": "cuda"}
        if best:
            fake = fake_driver_version(environ)
            if fake:
                best["driver_real"], best["driver"], best["driver_faked"] = best["driver"], fake, True
            best["cuda_variant"] = cuda_variant(system, best["driver"])
            if best["cuda_variant"] is None:
                best["backend"] = "vulkan"
            best["budget_mb"] = max(0, best["free_mb"] - VRAM_MARGIN_MB)
            if only == "nvidia":
                best["forced"] = "nvidia"
            return best
    if system == "Darwin" and only != "auto":
        # macOS has Apple GPUs (Metal) and, on old Intel Macs, an AMD card: only "amd" can match, via the branch below.
        result = _detect_mac(runner, machine, hidden) if only == "amd" else None
        if result and result["vendor"] == "AMD":
            result["forced"] = only
            return result
        return _forced_unavailable(only)
    if system == "Darwin":
        return _detect_mac(runner, machine, hidden) | visibility
    return detect_vulkan_gpu(system, runner, which, hidden, drm_root, environ, only) | visibility


# ------------------------------------------------ GPU memory (non-NVIDIA) ----

WINDOWS_GPU_MEMORY_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'; $ProgressPreference = 'SilentlyContinue'
$used = @{}
foreach ($s in (Get-Counter '\GPU Adapter Memory(*)\Dedicated Usage').CounterSamples) {
  if ($s.InstanceName -match 'luid_0x([0-9a-f]+)_0x([0-9a-f]+)_phys') {
    $key = [string]([uint64]([Convert]::ToUInt64($matches[1], 16) * 4294967296 + [Convert]::ToUInt64($matches[2], 16)))
    $used[$key] = [math]::Round($s.CookedValue / 1MB)
  }
}
$rows = @()
foreach ($k in (Get-ChildItem 'HKLM:\SOFTWARE\Microsoft\DirectX')) {
  $p = Get-ItemProperty $k.PSPath
  if ($p.Description -and $p.AdapterLuid -ne $null) {
    $luid = [string]([uint64]$p.AdapterLuid)
    if ($used.ContainsKey($luid)) {
      $rows += [pscustomobject]@{ name = $p.Description; total_mb = [math]::Round($p.DedicatedVideoMemory / 1MB); used_mb = $used[$luid] }
    }
  }
}
ConvertTo-Json -Compress -InputObject @($rows)
"""


def windows_gpu_memory(runner=subprocess.run):
    """[{name, total_mb, used_mb}] for each display adapter, from Windows itself (works for AMD/Intel/NVIDIA).

    Dedicated size comes from the DirectX registry key (a real 64-bit value, unlike Win32_VideoController's
    4 GB cap) and live usage from the GPU Adapter Memory performance counters, joined on the adapter LUID."""
    out = _run(["powershell", "-NoProfile", "-Command", WINDOWS_GPU_MEMORY_SCRIPT], runner, timeout=30) or ""
    start = out.find("[")
    if start < 0:
        return []
    try:
        rows = json.loads(out[start:out.rindex("]") + 1])
    except ValueError:
        return []
    result = []
    for row in rows if isinstance(rows, list) else []:
        try:
            result.append({"name": str(row["name"]), "total_mb": int(row["total_mb"]),
                           "used_mb": int(row["used_mb"]), "source": "windows-gpu-counters"})
        except (KeyError, TypeError, ValueError):
            continue
    return result


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"\((?:r|tm)\)", "", (name or "").lower()))


def match_adapter(rows, name):
    """The one row whose adapter name is `name` (ignoring case, punctuation and (R)/(TM)); None if there is no
    match or several (two identical cards cannot be told apart by name, so no measurement is better than a guess)."""
    key = _name_key(name)
    hits = [row for row in rows
            if key and _name_key(row.get("name")) and (key in _name_key(row["name"]) or _name_key(row["name"]) in key)]
    return hits[0] if len(hits) == 1 else None


def linux_amd_memory(drm_root="/sys/class/drm"):
    """Dedicated VRAM of the AMD GPU with the most memory (the discrete card, not an iGPU carve-out), from
    amdgpu's sysfs files, or None. lspci names are not mapped to sysfs cards, so the biggest card is assumed."""
    root = Path(drm_root)
    best = None
    try:
        cards = sorted(root.glob("card[0-9]*/device"))
    except OSError:
        return None
    for dev in cards:
        try:
            if (dev / "vendor").read_text().strip().lower() != "0x1002":
                continue
            total = int((dev / "mem_info_vram_total").read_text())
            used = int((dev / "mem_info_vram_used").read_text())
        except (OSError, ValueError):
            continue
        row = {"total_mb": total // (1024 * 1024), "used_mb": used // (1024 * 1024), "source": "amdgpu-sysfs"}
        if best is None or row["total_mb"] > best["total_mb"]:
            best = row
    return best


def vendor_memory(vendor, name, runner=subprocess.run, system=None):
    """Measured {total_mb, used_mb} for a non-NVIDIA GPU, or None when this OS cannot say."""
    system = system or platform.system()
    if system == "Windows":
        return match_adapter(windows_gpu_memory(runner), name)
    if system == "Linux" and vendor == "AMD":
        return linux_amd_memory()
    return None


def vram_used_mb(gpu, runner=subprocess.run):
    """Dedicated VRAM currently in use on the chosen GPU (MiB), or None if it cannot be measured here."""
    if gpu.get("vendor") == "NVIDIA":
        return nvidia_total_used_mb(runner)
    if gpu.get("backend") == "vulkan":
        if platform.system() == "Linux" and gpu.get("vendor") == "AMD":
            used = gpu_memory_used_mb(gpu, runner)  # the exact DRM card detect_gpu chose, GTT included for an iGPU
            if used is not None or gpu.get("drm_card"):
                return used
        memory = vendor_memory(gpu.get("vendor"), gpu.get("name"), runner)
        return memory["used_mb"] if memory else None
    return None


def cuda_variant(system: str, driver: str):
    """Pick the llama.cpp CUDA build the driver can run, or None for Vulkan."""
    try:
        major = int(driver.split(".")[0])
    except (ValueError, IndexError):
        return None
    if system == "Linux":
        return "ubuntu-cuda-12.8-x64" if major >= 570 else None
    if system == "Windows":
        if major >= 580:
            return "win-cuda-13.5-x64"
        return "win-cuda-12.4-x64" if major >= 550 else None
    return None


# ----------------------------------------------------- existing servers ----

def port_owner_name(port: int, runner=subprocess.run, system=None) -> str:
    """Return only the *process name* listening on a loopback port (never argv)."""
    system = system or platform.system()
    if system == "Windows":
        out = _run(["powershell", "-NoProfile", "-Command",
                    f"$c=Get-NetTCPConnection -State Listen -LocalPort {int(port)} -ErrorAction SilentlyContinue|"
                    "Select-Object -First 1; if($c){(Get-Process -Id $c.OwningProcess).ProcessName}"], runner)
        return (out or "").strip()
    out = _run(["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-Fc"], runner)
    for line in (out or "").splitlines():
        if line.startswith("c"):
            return line[1:].strip()
    return ""


def looks_like_lmstudio(name: str) -> bool:
    low = name.lower().replace(" ", "")
    return "lmstudio" in low or low in ("lms", "lm-studio") or low.startswith("lmstudio")


def find_existing_servers(strict_ports=False, runner=subprocess.run, discover=None, owner=None):
    """Probe loopback candidates; protected ports only if clearly LM Studio."""
    discover = discover or gpu_link_discover.discover
    owner = owner or (lambda port: port_owner_name(port, runner))
    urls = [f"http://127.0.0.1:{port}" for port in CANDIDATE_PORTS]
    allow_protected = False
    if not strict_ports and looks_like_lmstudio(owner(LMSTUDIO_DEFAULT_PORT)):
        urls.insert(0, f"http://127.0.0.1:{LMSTUDIO_DEFAULT_PORT}")
        allow_protected = True
    found = discover(tuple(urls), allow_protected)
    return [b for b in found if b.get("kind") != "Ollama"]


def estimate_params_b(name: str):
    match = re.search(r"(\d+(?:\.\d+)?)\s*[bB](?![a-z])", name.replace("_", "-"))
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    return value if 0.1 <= value <= 1000 else None


def is_coder(name: str) -> bool:
    return bool(CODER.search(name))


def choose_server_model(backend, budget_mb):
    """Pick a chat model from an existing server's list, preferring a fit and chat over coder."""
    models = [m for m in backend.get("models", []) if not SKIP_GGUF.search(m)]
    chat = [m for m in models if not is_coder(m)]
    models = chat or models
    if not models:
        return None
    sized = []
    for model in models:
        params = estimate_params_b(model)
        need = int(params * 620 + 1200) if params else None  # ~Q4 + cache
        sized.append((model, params, need))
    fits = [s for s in sized if s[2] is not None and s[2] <= budget_mb]
    if fits:
        return max(fits, key=lambda s: s[1])[0]
    unknown = [s for s in sized if s[2] is None]
    return (unknown or sorted(sized, key=lambda s: s[1] or 0))[0][0]


# -------------------------------------------------------------- models ----

def model_dirs(home=None, here=None):
    home = Path(home or Path.home())
    here = Path(here or data_dir())
    dirs = [here / "models", home / ".lmstudio" / "models",
            home / ".cache" / "lm-studio" / "models", home / ".cache" / "llama.cpp",
            home / "models", home / "Models"]
    if not FROZEN:
        dirs.insert(1, HERE.parent / "models")
    extra = os.environ.get("OPOS_GPU_LINK_MODELS_DIR")
    if extra:
        dirs.insert(0, Path(extra))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        dirs.append(Path(local) / "llama.cpp")
    return dirs


def maker_of(name: str) -> str:
    low = name.lower()
    for key, maker in MAKERS:
        if key in low:
            return maker
    return "Local"


def served_model_label(*parts) -> str | None:
    """Return a lead_label that satisfies proto.valid_model_label, or None.

    Existing-server ids and raw file names can include non-ASCII or control
    characters. The status worker rejects those with ToolError, so sanitize
    here and skip unusable values instead of crashing the companion loop.
    """
    for part in parts:
        if not isinstance(part, str):
            continue
        cleaned = "".join(ch if " " <= ch <= "~" else " " for ch in part)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()[:64]
        if cleaned:
            return cleaned
    return None


def label_of(name: str) -> str:
    stem = re.sub(r"(?i)\.gguf$", "", name)
    stem = re.sub(r"(?i)[-_.](q\d\w*|f16|bf16|ud|gguf)\b", "", stem)
    stem = re.sub(r"[^A-Za-z0-9. -]", " ", stem.replace("_", " "))
    return re.sub(r"\s+", " ", stem).strip()[:40] or "Local model"


def scan_local_ggufs(dirs, max_depth=5):
    found, seen = [], set()
    for root in dirs:
        root = Path(root)
        if not root.is_dir():
            continue
        base_depth = len(root.parts)
        for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
            if len(Path(dirpath).parts) - base_depth >= max_depth:
                dirnames[:] = []
            for name in filenames:
                if not name.lower().endswith(".gguf") or SKIP_GGUF.search(name):
                    continue
                path = Path(dirpath) / name
                try:
                    real = path.resolve()
                    size = real.stat().st_size
                except OSError:
                    continue
                if real in seen or size < 200 * 1024 * 1024:
                    continue
                seen.add(real)
                found.append({"path": str(path), "size_mb": size // (1024 * 1024), "name": name,
                              "label": label_of(name), "maker": maker_of(name)})
    return found


# ------------------------------------------------- RX 580 / old Mac profile ----
# Measured on a Mac Pro 5,1 (Intel Mac, RX 580 8 GB, MoltenVK, macOS Monterey): Vulkan with default settings
# returns blank or junk text for Gemma 3 / Qwen3 / any Q4-Q6 K-quant, and junk with flash attention on "auto".
# What does answer correctly on that GPU: Q8_0 files of Qwen2.5 and Llama 3.2 with flash attention OFF
# (about 3x the CPU speed). So on such a Mac we only choose those and add "-fa off".
PROFILE_RX580 = "rx580-old-mac"
RX580_GPU = re.compile(r"\bRX\s*(?:4[4-9]0|5[4-9]0)\b", re.I)  # Polaris: RX 460-490, 540-590
RX580_LOCAL_OK = re.compile(r"(?=.*(?:qwen2\.?5|llama[-_ ]?3\.[12]))(?=.*q8_0)", re.I)


def gpu_profile(gpu, system=None, machine=None, environ=None):
    """Name of the quirk profile for this GPU, or None. OPOS_GPU_LINK_PROFILE=rx580 forces it, =none disables."""
    environ = os.environ if environ is None else environ
    forced = (environ.get("OPOS_GPU_LINK_PROFILE") or "").strip().lower()
    if forced in ("none", "off", "0"):
        return None
    if forced in ("rx580", PROFILE_RX580):
        return PROFILE_RX580
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    if (system == "Darwin" and machine in ("x86_64", "amd64") and gpu.get("vendor") == "AMD"
            and RX580_GPU.search(gpu.get("name") or "")):
        return PROFILE_RX580
    return None


def profile_catalog(profile, role):
    if profile == PROFILE_RX580:
        return tuple(catalog_entry(r) for r in pins.RX580_MODELS if r["role"] == role)
    return None


def profile_local_ok(profile, local):
    """Local files the profile trusts (others are known to give blank/junk text on that GPU)."""
    if profile == PROFILE_RX580:
        return [m for m in local if RX580_LOCAL_OK.search(m["name"])]
    return list(local)


def moltenvk_env(env, system=None, home=None, binary=None):
    """Point the Vulkan loader at MoltenVK when the caller has not set up Vulkan themselves; without it
    llama.cpp lists no GPU and silently uses the CPU. The MoltenVK that ships next to our own no-AVX build
    (<runtime>/share/vulkan/icd.d, see ensure_noavx_vulkan) wins over the LunarG SDK in ~/VulkanSDK/macOS."""
    system = system or platform.system()
    if system != "Darwin" or env.get("VK_ICD_FILENAMES") or env.get("VK_DRIVER_FILES"):
        return env
    roots = []
    if binary is not None:
        roots.append(Path(binary).resolve().parent.parent)
    roots.append(Path(home or Path.home()) / "VulkanSDK" / "macOS")
    for root in roots:
        icd = root / "share" / "vulkan" / "icd.d" / "MoltenVK_icd.json"
        if icd.is_file():
            env = dict(env)
            env["VK_ICD_FILENAMES"] = env["VK_DRIVER_FILES"] = str(icd)
            lib = str(root / "lib")
            env["DYLD_LIBRARY_PATH"] = lib + (os.pathsep + env["DYLD_LIBRARY_PATH"] if env.get("DYLD_LIBRARY_PATH") else "")
            return env
    return env


def need_mb(size_mb: int, ctx: int = CTX) -> int:
    """Weights + KV cache (scales with model size) + compute buffers, conservatively."""
    return int(size_mb * 1.15 + 800 + ctx * size_mb / 40000)


def catalog_entry(row):
    return dict(row, size_mb=row["size"] // (1024 * 1024), name=row["file"])


def pick_model(budget_mb: int, local, catalog=None, prefer=None, max_mb=None):
    """Pick the main model. Returns ("local", entry) or ("download", catalog entry).

    Chat/instruct models come first: coder-tuned files are only used when you
    name them with --model-path, or when nothing else exists at all.
    """
    catalog = tuple(catalog) if catalog is not None else tuple(
        catalog_entry(r) for r in pins.MODELS if r["role"] == "main")
    every_local = list(local)
    if prefer:
        for entry in every_local:
            if prefer.lower() in entry["name"].lower() or prefer == entry["path"]:
                return "local", entry
    chat_local = [m for m in every_local if not is_coder(m["name"])]
    local = chat_local
    if max_mb:
        local = [m for m in local if m["size_mb"] <= max_mb]
        catalog = tuple(c for c in catalog if c["size_mb"] <= max_mb) or catalog[-1:]
    fits = [m for m in local if need_mb(m["size_mb"]) <= budget_mb]
    best_catalog = next((c for c in catalog if need_mb(c["size_mb"]) <= budget_mb), None)
    if fits:
        best_local = max(fits, key=lambda m: m["size_mb"])
        # Prefer a local file unless the catalog one is much bigger (better demo).
        if best_catalog is None or best_local["size_mb"] >= best_catalog["size_mb"] * 0.5:
            return "local", best_local
    if best_catalog is not None:
        return "download", best_catalog
    if chat_local:
        # Nothing fits. Take the smallest thing we can get, not just the smallest local file: a 1.7 GB local
        # model on a card with 1.8 GB free spills out of VRAM, while the 0.8 GB catalog model fits.
        smallest_local = min(chat_local, key=lambda m: m["size_mb"])
        if not catalog or smallest_local["size_mb"] <= catalog[-1]["size_mb"] * 1.25:
            return "local", smallest_local
        return "download", catalog[-1]
    if every_local and not catalog:
        return "local", min(every_local, key=lambda m: m["size_mb"])
    return "download", catalog[-1]


def pick_extras(budget_left_mb: int, main, local, catalog=None, limit=MAX_EXTRAS):
    """Choose up to `limit` smaller extra lanes (the demo's g1/g2).

    Each extra is a chat model no bigger than ~the main one, from a maker not yet
    used, that still fits in the memory left. Local files first, else the catalog.

    Largest-first packing can waste a lane: on a 16 GB card that already has
    ~6.2 GB in use, Qwen3-4B fits as the only extra, while Qwen3-1.7B + LFM2-1.2B
    would fill both extra panes. Prefer more lanes, then more local files, then
    larger total weights.
    """
    catalog = tuple(catalog) if catalog is not None else tuple(
        catalog_entry(r) for r in pins.MODELS if r["role"] == "extra")
    main_maker = main.get("maker") or maker_of(main.get("name", ""))
    main_path = main.get("path")
    cands = [dict(m, choice="local") for m in local
             if not is_coder(m["name"]) and m.get("path") != main_path]
    cands += [dict(c, choice="download") for c in catalog]
    cands = [c for c in cands if c["size_mb"] <= main["size_mb"] * 1.1]
    cands.sort(key=lambda c: (c["choice"] != "local", -c["size_mb"]))  # no download if a local file will do

    def _maker(cand):
        return cand.get("maker") or maker_of(cand["name"])

    feasible = []

    def rec(start, chosen, makers, need_sum):
        if chosen:
            feasible.append(list(chosen))
        if len(chosen) >= limit:
            return
        for i in range(start, len(cands)):
            cand = cands[i]
            maker = _maker(cand)
            if maker in makers:
                continue
            extra_need = need_mb(cand["size_mb"])
            if need_sum + extra_need > budget_left_mb:
                continue
            chosen.append(cand)
            makers.add(maker)
            rec(i + 1, chosen, makers, need_sum + extra_need)
            chosen.pop()
            makers.remove(maker)

    rec(0, [], {main_maker}, 0)
    if not feasible:
        return []

    def score(combo):
        return (len(combo),
                sum(1 for c in combo if c.get("choice") == "local"),
                sum(c["size_mb"] for c in combo))

    best = max(feasible, key=score)
    return sorted(best, key=lambda c: (c["choice"] != "local", -c["size_mb"]))


def _sidecar(path: Path) -> Path:
    return path.with_name(path.name + ".verified")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(4 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def verified_file(path: Path, sha256: str) -> bool:
    """True if the file matches the pin. A sidecar remembers a past full check."""
    try:
        st = path.stat()
    except OSError:
        return False
    side = _sidecar(path)
    token = f"{sha256} {st.st_size} {st.st_mtime_ns}"
    try:
        if side.read_text() == token:
            return True
    except OSError:
        pass
    if sha256_file(path) != sha256:
        return False
    try:
        side.write_text(token)
    except OSError:
        pass
    return True


def download(url: str, dest: Path, label: str, sha256: str, size=None) -> Path:
    """Fetch url to dest and refuse anything that does not match the pinned SHA-256."""
    if is_offline():
        raise RuntimeError(f"{label}: downloads are disabled (--offline)")
    if not sha256 or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise RuntimeError(f"{label}: refusing an unpinned download")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and verified_file(dest, sha256):
        return dest
    dest.unlink(missing_ok=True)
    part = dest.with_name(dest.name + ".part")
    say(f"Downloading {label} (one time) ...")
    request = urllib.request.Request(url, headers={"User-Agent": "opos-gpu-link"})
    h = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, part.open("wb") as out:
        total = int(response.headers.get("Content-Length") or size or 0)
        done, last = 0, 0.0
        while True:
            chunk = response.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            h.update(chunk)
            done += len(chunk)
            if time.monotonic() - last > 5:
                last = time.monotonic()
                say(f"  {label}: " + (f"{100 * done // total}%" if total else f"{done >> 20} MB"))
    if h.hexdigest() != sha256:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"{label}: SHA-256 mismatch, download discarded (not used)")
    part.replace(dest)
    verified_file(dest, sha256)
    return dest


def ensure_model(choice, entry, models_dir: Path, allow_download=True):
    if choice == "local":
        return Path(entry["path"]), entry.get("label") or entry["name"]
    if not allow_download:
        raise RuntimeError("No local model fits and downloads are disabled (--no-download)")
    url = f"https://huggingface.co/{entry['repo']}/resolve/main/{entry['file']}"
    return download(url, models_dir / entry["file"], entry["label"], entry["sha256"], entry["size"]), entry["label"]


# ------------------------------------------------------------- runtime ----

def llama_asset(system: str, machine: str, gpu) -> tuple[str, str | None]:
    """Return (llama asset suffix, cudart asset name template or None)."""
    machine = machine.lower()
    arm = machine in ("arm64", "aarch64")
    if system == "Darwin":
        return ("macos-arm64.tar.gz" if arm else "macos-x64.tar.gz"), None
    if system == "Linux":
        if gpu["backend"] == "cuda" and not arm:
            variant = gpu.get("cuda_variant") or "ubuntu-cuda-12.8-x64"
            return f"{variant}.tar.gz", f"cudart-llama-{{tag}}-bin-{variant}.tar.gz"
        if gpu["backend"] == "vulkan":
            return ("ubuntu-vulkan-arm64.tar.gz" if arm else "ubuntu-vulkan-x64.tar.gz"), None
        return ("ubuntu-arm64.tar.gz" if arm else "ubuntu-x64.tar.gz"), None
    if system == "Windows":
        if gpu["backend"] == "cuda":
            variant = gpu.get("cuda_variant") or "win-cuda-12.4-x64"
            return f"{variant}.zip", f"cudart-llama-bin-{variant}.zip"
        if gpu["backend"] == "vulkan":
            return "win-vulkan-x64.zip", None
        return ("win-cpu-arm64.zip" if arm else "win-cpu-x64.zip"), None
    raise RuntimeError(f"Unsupported OS {system}")


def llama_archive_names(system: str, machine: str, gpu) -> list[str]:
    """Pinned llama.cpp (and cudart, when needed) archive names for this OS/GPU."""
    suffix, cudart = llama_asset(system, machine, gpu)
    names = [f"llama-{LLAMA_TAG}-bin-{suffix}"]
    if cudart:
        names.append(cudart.format(tag=LLAMA_TAG))
    return names


def official_bundle_llama_gpus(system: str, machine: str):
    """GPU plans whose llama.cpp archives the one-file app carries for a fresh offline start.

    Darwin already embeds a runtime (Metal on arm64; no-AVX Vulkan on x86_64). Windows and
    Linux one-file builds were adb-only, so a fresh --offline start failed with
    "llama-server not found". Both CUDA and Vulkan are packed so the running machine can
    pick. Windows CUDA 12.4 is not packed (it would nearly double the bundle); those
    drivers can use the bundled Vulkan offline, or download 12.4 when online.
    """
    machine = machine.lower()
    if system == "Windows" and machine in ("amd64", "x86_64"):
        return ({"backend": "vulkan"},
                {"backend": "cuda", "cuda_variant": "win-cuda-13.5-x64"})
    if system == "Linux" and machine in ("x86_64", "amd64"):
        return ({"backend": "vulkan"},
                {"backend": "cuda", "cuda_variant": "ubuntu-cuda-12.8-x64"})
    return ()


def official_bundle_llama_archives(system: str, machine: str) -> list[str]:
    names, seen = [], set()
    for gpu in official_bundle_llama_gpus(system, machine):
        for name in llama_archive_names(system, machine, gpu):
            if name not in seen:
                seen.add(name)
                names.append(name)
    return names


def bundled_llama_archive(name: str, resources=None) -> Path | None:
    root = Path(resources) if resources is not None else RESOURCES
    path = root / "bundled" / "llama-archives" / name
    return path if path.is_file() else None


def bundled_llama_archive_facts(resources=None) -> list[dict]:
    root = Path(resources) if resources is not None else RESOURCES
    folder = root / "bundled" / "llama-archives"
    if not folder.is_dir():
        return []
    rows = []
    for path in sorted(folder.iterdir()):
        if not path.is_file():
            continue
        pin = pins.LLAMA.get(path.name)
        digest = sha256_file(path)
        rows.append({"name": path.name, "present": True,
                     "sha256_ok": bool(pin) and digest == pin["sha256"],
                     "size": path.stat().st_size})
    return rows


def _exe(name, system=None):
    """Suffix .exe when the *target* OS is Windows, including tests run on another OS."""
    windows = (system == "Windows") if system is not None else (os.name == "nt")
    return name + (".exe" if windows else "")


def _llama_server_names(system=None):
    """Filenames find_llama_server should accept. Windows prefers .exe but also a
    suffix-less file (hand-placed trees and tests run on another OS)."""
    if (system or platform.system()) == "Windows":
        return ("llama-server.exe", "llama-server")
    return ("llama-server",)


def ensure_exec(path: Path) -> None:
    """Bundled files may lose their execute bit when unpacked; restore it."""
    if os.name != "nt":
        try:
            if path.is_dir():
                for f in path.rglob("*"):
                    if f.is_file() and not f.is_symlink() and (f.name.startswith("llama") or f.name == "adb"):
                        f.chmod(f.stat().st_mode | 0o755)
            elif path.is_file():
                path.chmod(path.stat().st_mode | 0o755)
        except OSError:
            pass


_RUNTIME_DIR = re.compile(r"^llama-b\d+-(.+)$")  # folders this launcher downloads: llama-<tag>-<variant>


def _runtime_variant(runtime_dir: Path, binary: Path):
    """The variant folder name (e.g. "win-vulkan-x64") a downloaded runtime lives in, else None."""
    try:
        first = binary.relative_to(runtime_dir).parts[0]
    except (ValueError, IndexError):
        return None
    match = _RUNTIME_DIR.match(first)
    return match.group(1) if match else None


def find_llama_server(runtime_dir: Path, which=shutil.which, gpu=None, system=None, machine=None):
    """Locate llama-server. With `gpu`, only a runtime built for that GPU's variant counts: a cached Vulkan
    build must not be used for a CUDA plan (it ran on both GPUs and ignored the CUDA choice), nor the reverse.
    A runtime placed in the folder by hand (not a llama-<tag>-<variant> folder) is still accepted."""
    system = system or platform.system()
    env = os.environ.get("OPOS_LLAMA_SERVER")
    if env and Path(env).is_file():
        return Path(env)
    if runtime_dir.is_dir():
        hits = sorted(h for name in _llama_server_names(system) for h in runtime_dir.rglob(name))
        if gpu is not None:
            try:
                suffix = llama_asset(system or platform.system(), machine or platform.machine(), gpu)[0]
            except RuntimeError:
                suffix = None
            wanted = re.sub(r"[.](tar[.]gz|zip)$", "", suffix) if suffix else None
            mine = [h for h in hits if wanted and _runtime_variant(runtime_dir, h) == wanted]
            hits = mine or [h for h in hits if _runtime_variant(runtime_dir, h) is None]
        if hits:
            return hits[-1]
    bundled = RESOURCES / "bundled" / "llama"
    if bundled.is_dir():
        hits = sorted(h for name in _llama_server_names(system) for h in bundled.rglob(name))
        if hits:
            ensure_exec(bundled)
            return hits[-1]
    path = which("llama-server")
    return Path(path) if path else None


def library_dirs(binary: Path, extra_roots=()):
    """Every directory next to/under the runtime that holds shared libraries."""
    dirs = []
    roots = [binary.parent, binary.parent.parent, *extra_roots]
    for root in roots:
        root = Path(root)
        if not root.is_dir():
            continue
        for candidate in [root, *[p for p in root.iterdir() if p.is_dir()]]:
            try:
                names = os.listdir(candidate)
            except OSError:
                continue
            if any(n.endswith((".so", ".dylib", ".dll")) or ".so." in n for n in names):
                if candidate not in dirs:
                    dirs.append(candidate)
    return dirs


def runtime_env(binary: Path, system=None, base_env=None):
    """llama-server's CUDA libs are not found by default -> silent CPU fallback.

    Put the runtime directory and any cudart directory on the loader path.
    """
    system = system or platform.system()
    env = dict(base_env if base_env is not None else os.environ)
    env.pop(KEY_ENV, None)  # the key goes to the server only through a private file
    dirs = [str(d) for d in library_dirs(binary)]
    key = {"Linux": "LD_LIBRARY_PATH", "Windows": "PATH"}.get(system, "DYLD_LIBRARY_PATH")
    if dirs:
        env[key] = os.pathsep.join(dirs + ([env[key]] if env.get(key) else []))
    return env


def no_avx_mac_without_profile(gpu, system=None, machine=None, environ=None, avx=None) -> bool:
    """An Intel Mac whose CPU lacks AVX and whose GPU has no profile (and no OPOS_LLAMA_SERVER override)."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    environ = os.environ if environ is None else environ
    if (system != "Darwin" or machine not in ("x86_64", "amd64") or environ.get("OPOS_LLAMA_SERVER")
            or gpu.get("profile")):
        return False
    return not (cpu_has_avx() if avx is None else avx)


def wants_noavx_vulkan(gpu, system=None, machine=None, environ=None) -> bool:
    """An Intel Mac with the RX 580 profile, or any Intel Mac without AVX (CPU lane): the official macOS x64
    llama.cpp has no Vulkan and needs AVX, so both use GPU Link's own no-AVX build."""
    system = system or platform.system()
    machine = (machine or platform.machine()).lower()
    environ = os.environ if environ is None else environ
    if environ.get("OPOS_LLAMA_SERVER"):
        return False
    return (system == "Darwin" and machine in ("x86_64", "amd64")
            and (gpu.get("profile") == PROFILE_RX580 or bool(gpu.get("noavx_cpu"))))


def bundled_noavx_archive(pin=None):
    pin = pin or pins.NOAVX_VULKAN_MACOS_X64
    if not pin:
        return None
    path = RESOURCES / "bundled" / pin["name"]
    return path if path.is_file() else None


def noavx_tree_ok(root: Path, pin) -> bool:
    """Every file of the pinned artifact is present with the pinned SHA-256 (and nothing else is trusted)."""
    for rel, digest in pin["files"].items():
        path = root / rel
        if not path.is_file() or path.is_symlink() or sha256_file(path) != digest:
            return False
    return True


def ensure_noavx_vulkan(runtime_dir: Path, allow_download=True, pin=None, archive=None):
    """Return the llama-server of GPU Link's own no-AVX Vulkan/MoltenVK build, unpacking it on first use.

    Source of the .tar.gz: the copy packed into this bundle, else the pinned mirror URL (if any).
    The archive must match its pinned SHA-256 before anything is unpacked, and each unpacked file is checked
    against the pinned list, every run. Returns None when this program carries no such artifact (run from
    source); raises RuntimeError when an artifact is there but fails a check (it is never used)."""
    pin = pin or pins.NOAVX_VULKAN_MACOS_X64
    if not pin:
        return None
    target = runtime_dir / pin["dir"]
    binary = target / "bin" / "llama-server"
    if binary.is_file() and noavx_tree_ok(target, pin):
        ensure_exec(target)
        return binary
    archive = archive if archive is not None and Path(archive).is_file() else bundled_noavx_archive(pin)
    cleanup = False
    if archive is None:
        if not (pin.get("url") and allow_download):
            return None
        archive = download(pin["url"], runtime_dir / pin["name"], pin["name"], pin["sha256"], pin.get("size"))
        cleanup = True
    if sha256_file(archive) != pin["sha256"]:
        raise RuntimeError(f"{pin['name']}: SHA-256 mismatch, not unpacked (not used)")
    runtime_dir.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".unpack-", dir=runtime_dir))
    try:
        extract(archive, staging)
        unpacked = staging / pin["dir"]
        if not noavx_tree_ok(unpacked, pin):
            raise RuntimeError(f"{pin['name']}: unpacked files do not match the pinned list (not used)")
        shutil.rmtree(target, ignore_errors=True)
        unpacked.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        if cleanup:
            archive.unlink(missing_ok=True)
            _sidecar(archive).unlink(missing_ok=True)
    for path in target.rglob("*"):
        if path.is_file() and not path.is_symlink():
            path.chmod(path.stat().st_mode | (0o755 if path.parent.name == "bin" else 0o644))
    if platform.system() == "Darwin":
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(target)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return binary


def ensure_bundled_llama_archives(runtime_dir: Path, gpu, system=None, machine=None):
    """Unpack the matching bundled llama.cpp archives into runtime_dir. Return llama-server or None.

    None means this program does not carry a complete archive set for this GPU (run from source,
    or a CUDA 12.4 Windows driver). Raises RuntimeError when an archive is present but fails its
    checksum, or unpacks without llama-server; it is never used in that case.
    """
    system = system or platform.system()
    machine = machine or platform.machine()
    try:
        names = llama_archive_names(system, machine, gpu)
        suffix = llama_asset(system, machine, gpu)[0]
    except RuntimeError:
        return None
    archives = []
    for name in names:
        archive = bundled_llama_archive(name)
        pin = pins.LLAMA.get(name)
        if archive is None or not pin:
            return None
        if sha256_file(archive) != pin["sha256"]:
            raise RuntimeError(f"{name}: SHA-256 mismatch, not unpacked (not used)")
        archives.append(archive)
    # Already unpacked from a previous start? Don't touch PATH or OPOS_LLAMA_SERVER here.
    found = find_llama_server(runtime_dir, which=lambda _: None, gpu=gpu, system=system, machine=machine)
    if found is not None:
        return found
    runtime_dir.mkdir(parents=True, exist_ok=True)
    target = runtime_dir / f"llama-{LLAMA_TAG}-{re.sub(r'[.](tar[.]gz|zip)$', '', suffix)}"
    staging = Path(tempfile.mkdtemp(prefix=".unpack-llama-", dir=runtime_dir))
    try:
        for archive in archives:
            extract(archive, staging)
        shutil.rmtree(target, ignore_errors=True)
        staging.replace(target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    found = find_llama_server(runtime_dir, which=lambda _: None, gpu=gpu, system=system, machine=machine)
    if found is None:
        raise RuntimeError("bundled llama.cpp did not contain llama-server")
    ensure_exec(target)
    return found


def ensure_llama_server(runtime_dir: Path, gpu, system=None, machine=None, allow_download=True):
    system = system or platform.system()
    machine = machine or platform.machine()
    if wants_noavx_vulkan(gpu, system, machine):
        binary = ensure_noavx_vulkan(runtime_dir, allow_download)
        if binary is not None:
            return binary
    binary = find_llama_server(runtime_dir, gpu=gpu, system=system, machine=machine)
    if binary is not None:
        return binary
    bundled = ensure_bundled_llama_archives(runtime_dir, gpu, system, machine)
    if bundled is not None:
        return bundled
    if not allow_download:
        raise RuntimeError("llama-server not found and downloads are disabled")
    suffix, cudart = llama_asset(system, machine, gpu)
    target = runtime_dir / f"llama-{LLAMA_TAG}-{re.sub(r'[.](tar[.]gz|zip)$', '', suffix)}"
    names = [f"llama-{LLAMA_TAG}-bin-{suffix}"] + ([cudart.format(tag=LLAMA_TAG)] if cudart else [])
    for name in names:
        pin = pins.LLAMA.get(name)
        if not pin:
            raise RuntimeError(f"{name}: no pinned checksum for this platform; use OPOS_LLAMA_SERVER")
        archive = download(GITHUB_RELEASE.format(tag=LLAMA_TAG, name=name), runtime_dir / name, name,
                           pin["sha256"], pin["size"])
        extract(archive, target)
        archive.unlink(missing_ok=True)
        _sidecar(archive).unlink(missing_ok=True)
    binary = find_llama_server(runtime_dir, gpu=gpu, system=system, machine=machine)
    if binary is None:
        raise RuntimeError("llama.cpp download did not contain llama-server")
    return binary


def extract(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    root = target.resolve()
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                dest = (target / info.filename).resolve()
                if root not in dest.parents and dest != root:
                    raise RuntimeError("unsafe path in archive")
                z.extract(info, target)
                mode = (info.external_attr >> 16) & 0o777
                if mode:
                    os.chmod(dest, mode)
    else:
        with tarfile.open(archive) as t:
            for member in t.getmembers():
                dest = (target / member.name).resolve()
                if root not in dest.parents and dest != root:
                    raise RuntimeError("unsafe path in archive")
            try:
                t.extractall(target, filter="tar")
            except TypeError:
                t.extractall(target)
    if os.name != "nt":
        for path in target.rglob("*"):
            if path.is_file() and (path.name.startswith(("llama", "adb", "fastboot"))
                                   and "." not in path.name):
                path.chmod(path.stat().st_mode | 0o755)
        if platform.system() == "Darwin":
            subprocess.run(["xattr", "-dr", "com.apple.quarantine", str(target)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)


def probe_binary(binary: Path, env, runner=subprocess.run):
    """Run `llama-server --version`. Returns (ok, detail); detail names why it cannot run."""
    try:
        result = runner([str(binary), "--version"], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        timeout=60, check=False, env=env)
    except (OSError, subprocess.TimeoutExpired) as error:
        return False, f"could not run: {type(error).__name__}"
    text = result.stdout.decode("utf-8", "replace")
    if result.returncode == 0:
        lines = text.strip().splitlines()
        return True, lines[-1] if lines else ""
    if result.returncode in (-4, 132, 3221225501):
        return False, "illegal instruction (this CPU lacks instructions the build needs, e.g. AVX)"
    loader = next((l.strip() for l in text.splitlines()
                   if re.search(r"Symbol not found|Library not loaded|cannot open shared object|"
                                r"version `GLIBC|DLL was not found|entry point", l)), "")
    if loader:
        return False, "the system libraries are too old or missing: " + loader[:160]
    return False, f"crashed with code {result.returncode}"


def list_devices(binary: Path, env, runner=subprocess.run):
    """Devices llama.cpp can actually use with this env (CUDA0, MTL0, Vulkan0...)."""
    out = _run([str(binary), "--list-devices"], runner, timeout=60, env=env) or ""
    return [line.strip() for line in out.splitlines()
            if re.match(r"\s*(CUDA|MTL|Metal|Vulkan|ROCm|HIP|SYCL)\d*\s*:", line)]


def pick_vulkan_device(devices, gpu):
    """The `VulkanN` id of the chosen GPU when several Vulkan devices exist (e.g. an AMD and an NVIDIA card).

    Without it llama.cpp uses Vulkan0, which may be the card we did not choose. Returns None when there is
    one device, when the backend is not Vulkan, or when no device name matches (the caller then warns)."""
    if gpu.get("backend") != "vulkan":
        return None
    vulkan = []
    for line in devices or []:
        m = re.match(r"\s*(Vulkan\d+)\s*:\s*(.*?)\s*(?:\(\d+ MiB.*)?$", line)
        if m:
            vulkan.append((m.group(1), m.group(2)))
    if len(vulkan) < 2:
        return None
    wanted = _name_key(gpu.get("name"))
    hits = [dev for dev, name in vulkan if wanted and (wanted in _name_key(name) or _name_key(name) in wanted)]
    if len(hits) == 1:
        return hits[0]
    vendor_words = {"AMD": ("amd", "radeon"), "NVIDIA": ("nvidia", "geforce"), "Intel": ("intel", "arc")}.get(
        gpu.get("vendor"), ())
    hits = [dev for dev, name in vulkan if any(w in name.lower() for w in vendor_words)]
    return hits[0] if len(hits) == 1 else None


def classify_devices(lines, hide=False):
    return [line for line in lines
            if not SOFTWARE_GPU.search(line)
            and not re.match(r"\s*\w+\d*\s*:\s*CPU\s*(?:\(.*\))?\s*$", line, re.I)  # a bare "CPU" device, not "...Processor"
            and not (hide and (NVIDIA_NAME.search(line) or CUDA_DEVICE.match(line)))]


def hide_nvidia_env(env, *, system=None, icd_dirs=None):
    """Mask CUDA and restrict the Linux Vulkan loader to non-NVIDIA ICDs."""
    env = dict(env, CUDA_VISIBLE_DEVICES="")
    if (system or platform.system()) != "Linux":
        return env
    if icd_dirs is None:
        icd_dirs = (Path("/etc/vulkan/icd.d"), Path("/usr/share/vulkan/icd.d"),
                    Path("/usr/local/share/vulkan/icd.d"), Path.home() / ".local/share/vulkan/icd.d")
    manifests = []
    for directory in icd_dirs:
        try:
            files = sorted(Path(directory).glob("*.json"))
        except OSError:
            continue
        for path in files:
            if NVIDIA_ICD.search(path.name):
                continue
            try:
                library = json.loads(path.read_text())["ICD"]["library_path"]
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if isinstance(library, str) and library and not NVIDIA_ICD.search(library):
                manifests.append(str(path.absolute()))
    drivers = os.pathsep.join(dict.fromkeys(manifests)) or "/nonexistent/opos-no-nvidia-icd.json"
    env["VK_DRIVER_FILES"] = env["VK_ICD_FILENAMES"] = drivers
    if "GGML_VK_VISIBLE_DEVICES" in env:
        env["GGML_VK_VISIBLE_DEVICES"] = "0"  # indices now refer to the filtered driver set
    return env


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        if os.name != "nt":  # allow reuse of our own just-stopped server's port (TIME_WAIT)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) != 0


def choose_port(start=DEFAULT_LAUNCH_PORT, span=10, free=port_free, taken=()):
    for port in range(start, start + span):
        if port not in LAUNCH_FORBIDDEN and port not in taken and free(port):
            return port
    raise RuntimeError(f"No free port in {start}-{start + span - 1}")


class LaunchedServer:
    def __init__(self, process, port, log_path, alias=ALIAS):
        self.process, self.port, self.log_path, self.alias = process, port, log_path, alias

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.port}"

    def stop(self, quiet=False):
        if self.process.poll() is None:
            try:
                if os.name == "nt":
                    self.process.terminate()
                else:
                    self.process.send_signal(signal.SIGTERM)
                self.process.wait(15)
            except ProcessLookupError:
                pass  # The owned child exited between poll and signal.
            except subprocess.TimeoutExpired:
                try:
                    self.process.kill()
                    self.process.wait(5)
                except ProcessLookupError:
                    pass
        if not quiet:
            say(f"Local model server on port {self.port} stopped; model unloaded from GPU memory.")


def new_key() -> str:
    return secrets.token_urlsafe(32)


def write_key_file(key: str, directory: Path | None = None) -> Path:
    """A private file for llama-server's --api-key-file (mode 0600 in a 0700 folder)."""
    base = Path(tempfile.mkdtemp(prefix="opos-gl-", dir=directory))
    path = base / "k"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    return path


def server_command(binary, model_path, port, key_file, alias, backend, ctx=CTX, profile=None, device=None,
                   generation_overrides=None, environ=None):
    from gpu_link_gen import generation_flags

    ngl = "0" if backend == "cpu" else "999"
    # rx580-old-mac: "-fa off" (flash attention breaks Q8_0 lanes there) and "--no-kv-offload": with the KV cache on
    # the RX 580 both lanes turn to garbage ("@@@@", "8888", looped fragments) after about 540 generated tokens
    # (Mac Pro lab, receipts/macpro-rx580-long/); keeping the KV cache in system RAM stays correct (about 15 tok/s).
    quirks = ["-fa", "off", "--no-kv-offload"] if profile == PROFILE_RX580 else []
    if device and backend != "cpu" and re.fullmatch(r"[A-Za-z]+\d+", device):
        quirks += ["--device", device]
    return [str(binary), "-m", str(model_path), "--host", "127.0.0.1", "--port", str(port),
            "-ngl", ngl, "-c", str(ctx), "--alias", alias, "-np", str(SLOTS), "--jinja",
            "--api-key-file", str(key_file), "--cors-origins", "localhost",
            "--no-webui", "--no-slots", "-lv", "4", *quirks,
            *generation_flags(model_path, profile, generation_overrides, environ)]  # -lv 4 does not log prompts


def launch_llama_server(binary, model_path, port, env, log_dir: Path, backend, key_file, alias=ALIAS, ctx=CTX,
                        profile=None, device=None):
    if port in LAUNCH_FORBIDDEN:
        raise ValueError("Refusing a protected launch port")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"llama-server-{port}.log"
    cmd = server_command(binary, model_path, port, key_file, alias, backend, ctx, profile, device)
    model_size = Path(model_path).stat().st_size
    log = log_path.open("wb")
    kwargs = {"creationflags": 0x08000000} if os.name == "nt" else {"start_new_session": True}
    kwargs["cwd"] = os.getcwd()
    try:
        process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, **kwargs)
    finally:
        log.close()
    server = LaunchedServer(process, port, log_path, alias)
    server.launch = {"argv": tuple(cmd), "env": dict(env), "log_path": log_path,
                     "model_path": Path(model_path), "size": model_size,
                     "alias": alias, "port": port, "options": kwargs, "process": process, "pid": process.pid,
                     "backend": backend, "profile": profile, "device": device, "ctx": ctx}
    return server


def wait_healthy(server: LaunchedServer, timeout=240, cancelled=lambda: False):
    import http.client
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancelled():
            return False
        if server.process.poll() is not None:
            return False
        conn = http.client.HTTPConnection("127.0.0.1", server.port, timeout=2)
        try:
            conn.request("GET", "/health")
            status = conn.getresponse().status
            if status == 200:
                return True
        except (OSError, http.client.HTTPException):
            pass
        finally:
            conn.close()
        time.sleep(1)
    return False


OFFLOAD = re.compile(r"offloaded (\d+)/(\d+) layers to GPU")
GPU_BUFFER = re.compile(r"(CUDA\d|MTL\d|Metal|Vulkan\d|ROCm\d)\S*\s+model buffer size\s*=\s*([\d.]+) MiB")


def parse_offload_log(text: str):
    layers = None
    match = OFFLOAD.search(text)
    if match:
        layers = (int(match.group(1)), int(match.group(2)))
    buffers = [(m.group(1), float(m.group(2))) for m in GPU_BUFFER.finditer(text)]
    return {"layers": layers, "gpu_buffers_mib": buffers,
            "cpu_fallback_hint": ("no usable GPU found" in text.lower()
                                  or "ggml_cuda_init: failed" in text.lower()
                                  or "cuda error" in text.lower())}


def nvidia_pid_memory(pid: int, runner=subprocess.run):
    out = _run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                "--format=csv,noheader,nounits"], runner) or ""
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0] == str(pid):
            try:
                return int(parts[1])
            except ValueError:
                return None
    # Windows (WDDM) lists processes without per-process VRAM, or not at all: that is "unknown", not "zero".
    return 0 if out and platform.system() != "Windows" else None


def nvidia_total_used_mb(runner=subprocess.run):
    """Total VRAM in use on the best NVIDIA GPU (MiB), or None. Used where per-process VRAM is not reported."""
    out = _run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"], runner) or ""
    values = []
    for line in out.splitlines():
        try:
            values.append(int(float(line.strip())))
        except ValueError:
            pass
    return max(values) if values else None


def gpu_memory_used_mb(gpu, runner=subprocess.run, *, drm_root=None):
    """Read used VRAM, including GTT for an integrated AMD GPU, when reported."""
    if gpu["vendor"] == "NVIDIA":
        return nvidia_total_used_mb(runner)
    if gpu["vendor"] != "AMD" or (drm_root is None and platform.system() != "Linux"):
        return None
    cards = [card for card in read_drm_cards(DRM_ROOT if drm_root is None else drm_root)
             if card["vendor"] == "AMD"]
    name = gpu.get("drm_card")
    card = next((card for card in cards if card["card"] == name), None) if name else (
        cards[0] if len(cards) == 1 else None)
    if card is None:
        return None
    values = [card["vram_used_mb"]]
    if gpu.get("integrated"):
        values.append(card["gtt_used_mb"])
    measured = [value for value in values if value is not None]
    return sum(measured) if measured else None


def verify_gpu(server: LaunchedServer, gpu, runner=subprocess.run, devices=None, used_before=None):
    """Decide from evidence whether the model is on the GPU.

    "offloaded N/N layers" alone is NOT proof: llama.cpp prints it even when no
    GPU backend loaded (seen on the RTX 5080 without LD_LIBRARY_PATH). Require a
    GPU model buffer in the log, or VRAM held by this server's PID.
    """
    try:
        text = server.log_path.read_text("utf-8", "replace")
    except OSError:
        text = ""
    info = parse_offload_log(text)
    evidence = []
    if info["layers"]:
        evidence.append("offloaded {}/{} layers (not proof by itself)".format(*info["layers"]))
    gpu_buffer = any(m > 0 for _, m in info["gpu_buffers_mib"])
    if info["gpu_buffers_mib"]:
        evidence.append(", ".join(f"{d} model buffer {m:.0f} MiB" for d, m in info["gpu_buffers_mib"]))
    else:
        evidence.append("no GPU model buffer in the log")
    on_gpu = gpu_buffer
    if gpu["vendor"] == "NVIDIA" and gpu.get("backend") != "cpu":
        used = nvidia_pid_memory(server.process.pid, runner)
        if used is not None:
            evidence.append(f"nvidia-smi: {used} MiB for this server")
            on_gpu = used > 256  # VRAM held by this very process is direct proof either way
        elif used_before is not None:
            now = nvidia_total_used_mb(runner)
            if now is not None:
                rise = now - used_before
                evidence.append(f"nvidia-smi: total VRAM rose {rise} MiB after loading (per-process VRAM not reported)")
                on_gpu = rise > 256
    elif gpu.get("backend") == "vulkan" and used_before is not None:
        now = vram_used_mb(gpu, runner)
        if now is not None:
            rise = now - used_before
            evidence.append(f"dedicated VRAM on {gpu.get('name')} rose {rise} MiB after loading")
            buffers = sum(m for _, m in info["gpu_buffers_mib"])
            # a Vulkan buffer in the log AND real VRAM on the chosen card; a tiny model needs a smaller rise
            on_gpu = on_gpu and rise > max(32, min(256, buffers / 2))
    if devices is not None and not devices:
        evidence.append("llama.cpp listed no GPU devices")
        on_gpu = False
    if info["cpu_fallback_hint"]:
        evidence.append("log reports GPU init failure")
        on_gpu = False
    return on_gpu, evidence


# ------------------------------------------------------------------ adb ----

def adb_candidates(home=None, which=shutil.which):
    home = Path(home or Path.home())
    exe = _exe("adb")
    paths = []
    found = which("adb")
    if found:
        paths.append(Path(found))
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            paths.append(Path(os.environ[var]) / "platform-tools" / exe)
    paths += [data_dir() / "runtime" / "platform-tools" / exe,
              home / "Library" / "Android" / "sdk" / "platform-tools" / exe,
              home / "Android" / "Sdk" / "platform-tools" / exe,
              Path("/opt/homebrew/bin/adb"), Path("/usr/local/bin/adb"), Path("/usr/bin/adb")]
    if os.environ.get("LOCALAPPDATA"):
        paths.append(Path(os.environ["LOCALAPPDATA"]) / "Android" / "Sdk" / "platform-tools" / exe)
    # Last resort before downloading: the adb packed inside the bundle. It is
    # after the system adb on purpose, so a different adb version never
    # restarts an adb server the user already has running.
    paths.append(RESOURCES / "bundled" / "adb" / exe)
    return paths



def _decode_stdout(result) -> str:
    stdout = getattr(result, "stdout", None)
    if isinstance(stdout, (bytes, bytearray)):
        return stdout.decode("utf-8", "replace")
    return stdout or ""


def _usable_adb_binary(path: Path):
    """Return a resolved adb/adb.exe path, or None if this file is not usable."""
    if not path.is_file():
        return None
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    names = {path.name.lower(), resolved.name.lower()}
    if "adb" not in names and "adb.exe" not in names:
        return None
    return resolved


def is_bare_command(selected) -> bool:
    """True for a command name such as adb, not a relative or absolute path."""
    text = str(selected)
    return text == Path(text).name and not text.startswith(".")


def resolve_adb_path(selected):
    """Resolve an adb name or path. Bare names use PATH only, never the cwd.

    Explicit relative paths such as ./adb are returned as absolute paths so
    later subprocess calls do not treat them as a bare PATH command.
    """
    text = str(selected)
    if is_bare_command(text):
        found = shutil.which(text)
        if not found:
            return None
        try:
            return Path(found).resolve()
        except OSError:
            return Path(found)
    path = Path(text)
    if not path.is_file():
        return None
    try:
        return path.resolve()
    except OSError:
        return path


def running_adb_server_executable(runner=subprocess.run, system=None):
    """Return the adb binary that owns the already-running adb server, or None.

    A PATH or Homebrew adb can talk to a server started by a different install.
    Forwards created that way are owned by the server binary, so a later owner
    check against the selected executable fails and the phone's PC lane stays
    queued with no useful error. Prefer the live server's own binary. Windows
    uses the same Get-NetTCPConnection route as listener_owned_by_adb.
    """
    platform_name = system or sys.platform
    if platform_name in ("win32", "Windows"):
        return _running_adb_server_from_netstat(runner=runner)
    return _running_adb_server_from_lsof(runner=runner)


def _running_adb_server_from_lsof(runner=subprocess.run, port: int = 5037):
    try:
        listen = runner(
            ["lsof", "-nP", f"-iTCP:{int(port)}", "-sTCP:LISTEN", "-Fpn"],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if listen.returncode != 0:
        return None
    owners = set()
    pid = None
    for line in _decode_stdout(listen).splitlines():
        if line.startswith("p"):
            pid = line[1:] if line[1:].isdigit() else None
            continue
        if not line.startswith("n") or pid is None:
            continue
        host, sep, service = line[1:].rpartition(":")
        if not sep or service != str(int(port)):
            return None
        if host not in ("127.0.0.1", "[::1]"):
            return None
        owners.add(pid)
    if len(owners) != 1:
        return None
    owner = next(iter(owners))
    try:
        binary = runner(
            ["lsof", "-nP", "-a", "-p", owner, "-d", "txt", "-Fn"],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if binary.returncode != 0:
        return None
    for line in _decode_stdout(binary).splitlines():
        if not line.startswith("n"):
            continue
        found = _usable_adb_binary(Path(line[1:]))
        if found is not None:
            return found
    return None


def _running_adb_server_from_netstat(runner=subprocess.run, port: int = 5037):
    script = (
        "$ErrorActionPreference='Stop';"
        f"$p={int(port)};"
        "Get-NetTCPConnection -State Listen -LocalPort $p | ForEach-Object {"
        "$owner=Get-Process -Id $_.OwningProcess;"
        "Write-Output ($_.LocalAddress+'|'+$owner.Path)"
        "}"
    )
    try:
        result = runner(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    found = []
    for line in _decode_stdout(result).splitlines():
        if "|" not in line:
            continue
        address, raw = line.split("|", 1)
        if address not in ("127.0.0.1", "::1"):
            return None
        path = _usable_adb_binary(Path(raw.strip()))
        if path is None:
            return None
        found.append(path)
    unique = {os.path.normcase(str(path)) for path in found}
    if len(unique) != 1:
        return None
    return found[0]


def _same_adb(left: Path, right: Path) -> bool:
    try:
        first, second = left.resolve(), right.resolve()
    except OSError:
        first, second = left, right
    return os.path.normcase(str(first)) == os.path.normcase(str(second))


def prefer_running_adb_server(selected: Path, runner=subprocess.run, announce=None, system=None):
    """If an adb server is already running, use its executable so forwards pass the owner check."""
    server = running_adb_server_executable(runner=runner, system=system)
    chosen = resolve_adb_path(selected)
    if server is None:
        return chosen if chosen is not None else Path(str(selected))
    try:
        live = Path(server).resolve()
    except OSError:
        return chosen if chosen is not None else Path(str(selected))
    if chosen is not None and _same_adb(chosen, live):
        return live
    label = chosen if chosen is not None else selected
    msg = ("Using the already-running adb server's executable instead of "
           f"{label} so USB forwards belong to the same binary ({live}).")
    if announce is not None:
        announce(msg)
    else:
        say(msg)
    return live


def _adb_missing_error(explicit=None) -> RuntimeError:
    if explicit and not is_bare_command(explicit):
        where = "at %s" % explicit
    else:
        where = "on PATH"
    return RuntimeError("adb not found %s. Install Google's Android SDK "
                        "Platform-Tools (https://developer.android.com/tools/releases/platform-tools), "
                        "put adb on PATH or pass --adb PATH, or run once with --prefetch" % where)


def ensure_adb(runtime_dir: Path, explicit=None, allow_download=True, system=None, runner=subprocess.run):
    if explicit:
        chosen = resolve_adb_path(explicit)
        if chosen is None:
            # Bare names may still adopt a live server. An explicit missing path
            # is a typo and must not be silently replaced.
            if is_bare_command(explicit):
                live = running_adb_server_executable(runner=runner, system=system)
                if live is not None:
                    say("Using the already-running adb server's executable (%s)." % live)
                    return live
            raise _adb_missing_error(explicit)
        selected = prefer_running_adb_server(explicit, runner=runner, system=system)
        if selected.is_file():
            return selected
        raise _adb_missing_error(explicit)
    for path in adb_candidates():
        if path.is_file():
            if RESOURCES in path.parents:
                ensure_exec(path)
            return prefer_running_adb_server(path, runner=runner, system=system)
    live = running_adb_server_executable(runner=runner, system=system)
    if live is not None:
        say("Using the already-running adb server's executable (%s)." % live)
        return live
    if not allow_download:
        raise RuntimeError("adb not found and downloads are disabled. Install Google's Android SDK "
                           "Platform-Tools (https://developer.android.com/tools/releases/platform-tools), "
                           "put adb on PATH or pass --adb PATH, or run once with --prefetch")
    system = system or platform.system()
    os_name = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}[system]
    pin = pins.PLATFORM_TOOLS[os_name]
    archive = download(pin["url"], runtime_dir / f"platform-tools-{os_name}.zip",
                       "Android platform-tools (adb)", pin["sha256"], pin["size"])
    extract(archive, runtime_dir)
    archive.unlink(missing_ok=True)
    _sidecar(archive).unlink(missing_ok=True)
    adb = runtime_dir / "platform-tools" / _exe("adb")
    if not adb.is_file():
        raise RuntimeError("platform-tools download did not contain adb")
    return prefer_running_adb_server(adb, runner=runner, system=system)


PHONE_TEXT = {
    "none": ["Plug the phone in with a USB-C data cable and unlock it.",
             "If nothing happens: Settings > Developer options > USB debugging = On."],
    "unauthorized": ["Look at the phone: tap  Allow  on \"Allow USB debugging?\"",
                     "Tick \"Always allow from this computer\" so you are not asked again."],
    "no permissions": ["This computer may not use the phone over USB yet (Linux USB rules).",
                       "Install your distro's android-udev rules (e.g. sudo apt install android-sdk-platform-tools-common),",
                       "then unplug and replug the phone."],
    "offline": ["The phone is connected but offline. Unplug it, wait 2 seconds, plug it back in."],
    "many": ["More than one phone is connected. Unplug the extra one (or pass --serial)."],
}


def phone_state(adb: Path, runner=subprocess.run):
    """Return (state, serial) where state in none/unauthorized/no permissions/offline/many/device."""
    out = _run([str(adb), "devices", "-l"], runner, timeout=10)
    if out is None:
        return "none", None
    usb = []
    for line in out.splitlines()[1:]:
        fields = line.split()
        if len(fields) < 2:
            continue
        serial = fields[0]
        if serial.startswith("emulator-") or re.search(r":\d+$", serial) or "._tcp" in serial:
            continue
        rest = " ".join(fields[1:])
        if rest.startswith("no permissions"):
            usb.append(("no permissions", serial))
        else:
            usb.append((fields[1], serial))
    ready = [s for st, s in usb if st == "device"]
    if len(ready) > 1:
        return "many", None
    if ready:
        return "device", ready[0]
    for state in ("unauthorized", "no permissions", "offline"):
        hit = next((s for st, s in usb if st == state), None)
        if hit:
            return state, hit
    return "none", None


def wait_for_phone(adb: Path, runner=subprocess.run, sleep=time.sleep, timeout=None):
    last = None
    start = time.monotonic()
    _run([str(adb), "start-server"], runner, timeout=20)
    while True:
        state, serial = phone_state(adb, runner)
        if state == "device":
            say(f"Phone connected over USB ({serial[:4]}…).")
            return serial
        if state != last:
            banner(["PHONE: " + PHONE_TEXT[state][0], *PHONE_TEXT[state][1:]])
            last = state
        if timeout is not None and time.monotonic() - start > timeout:
            return None
        sleep(2)


# ---------------------------------------------------------------- main ----

MAC_PROFILER = "/usr/sbin/system_profiler"
# The phone's wire-label rule (gpu_link_proto.valid_label); test_gpu_link_autosetup checks they agree.
WIRE_LABEL = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9 -]{0,22}[A-Za-z0-9])?")


def _wire_words(text: str) -> str:
    text = re.sub(r"[^A-Za-z0-9 -]", " ", text or "")
    return re.sub(r"\s+", " ", text).strip(" -")


_MODEL_NAME_CACHE: list[str] = []


def mac_model_name(runner=None) -> str:
    """This Mac's model name ("MacBook Pro", "Mac mini"), or "" when it cannot be read.

    Reads the locale-independent machine_name from system_profiler's JSON once per process
    (5 s cap, stdin closed); a runner passed by a test is never cached."""
    if runner is None and _MODEL_NAME_CACHE:
        return _MODEL_NAME_CACHE[0]
    name = ""
    try:
        done = (runner or subprocess.run)([MAC_PROFILER, "-json", "SPHardwareDataType"], capture_output=True,
                                          text=True, stdin=subprocess.DEVNULL, timeout=5, check=False)
        if done.returncode == 0:
            items = json.loads(done.stdout or "{}").get("SPHardwareDataType") or []
            if isinstance(items, list) and items and isinstance(items[0], dict) and isinstance(items[0].get("machine_name"), str):
                name = _wire_words(items[0]["machine_name"])
    except (OSError, subprocess.SubprocessError, ValueError, AttributeError, TypeError):
        name = ""
    if runner is None:
        _MODEL_NAME_CACHE[:] = [name]
    return name


def safe_label(gpu, system=None, model_name=None) -> str:
    """The pairing label on the wire, also the phone's name for this computer.

    A Mac is named as a Mac ("M5 Pro MacBook Pro"); other computers stay "<GPU> PC". The phone
    keeps the label it saw at pairing, so a new label takes effect only at the next pairing
    (Forget on the phone, then --reset-pairing on the companion)."""
    name = re.sub(r"(?i)nvidia|geforce|apple|\(r\)|\(tm\)|corporation", "", gpu.get("name") or "")
    name = _wire_words(name)
    if (system or platform.system()) == "Darwin":
        model = _wire_words(mac_model_name() if model_name is None else model_name)
        noun = "MacBook" if model.lower().startswith("macbook") else "Mac"
        for label in (f"{name} {model}" if model else "", f"{name} {noun}", model, noun):
            label = label.strip()
            if WIRE_LABEL.fullmatch(label):
                return label
    label = (name + " PC").strip() if name else "GPU PC"
    label = label[:24].strip(" -")
    return label if WIRE_LABEL.fullmatch(label) else "GPU PC"


def ready_lines(gpu_name, lanes, noun):
    """The "ready" banner, naming this computer by noun ("MacBook", "Mac" or "PC")."""
    return ["GPU Link is ready.", f"Computer GPU: {gpu_name}",
            f"{noun} answer lanes: {len(lanes)} ({', '.join(l['label'] for l in lanes)})",
            "Open GPU Link on the phone and ask a question.",
            "First time only: compare the 6-digit code and tap Allow on the phone.",
            "Unplugging pauses the computer answers; plugging back in resumes them.",
            "Press Ctrl-C here to stop."]


def protected_flags(chat_url: str):
    """The r23 companion only accepts a protected port with an explicit opt-in."""
    _, _, port, _ = gpu_link_discover.probe_origin(chat_url.split("/v1")[0])
    if port in gpu_link_discover.PROTECTED_PORTS:
        return ["--probe-url", chat_url, "--allow-protected-port"]
    return []


def scan_roots(args):
    """Directories choose_models scans for local GGUFs, first one wins on duplicates.

    --models-dir is a first-class root (choose_models used to ignore it). An existing
    --model-path file contributes its parent. model_dirs() still adds data_dir/models,
    ~/.lmstudio/models, ~/.cache/lm-studio/models, ~/.cache/llama.cpp, ~/models,
    ~/Models, $OPOS_GPU_LINK_MODELS_DIR, and %LOCALAPPDATA%/llama.cpp.
    """
    roots = []
    models_dir = getattr(args, "models_dir", None)
    if models_dir:
        roots.append(Path(models_dir))
    model_path = getattr(args, "model_path", None)
    if model_path:
        path = Path(model_path)
        if path.is_file():
            roots.append(path.parent)
        elif path.is_dir():
            roots.append(path)
    roots.extend(model_dirs(here=getattr(args, "data_dir", None)))
    seen, out = set(), []
    for root in roots:
        try:
            key = str(Path(root).resolve())
        except OSError:
            key = str(Path(root))
        if key not in seen:
            seen.add(key)
            out.append(Path(root))
    return out


def _offline_choice(args):
    """True when --offline (or $OPOS_GPU_LINK_OFFLINE) is on. --no-download alone is not enough:
    start_runtime still records a catalog choice and then refuses the fetch."""
    return bool(getattr(args, "offline", False) or is_offline())


def choose_models(args, gpu, profile):
    local = scan_local_ggufs(scan_roots(args))
    if profile and not args.model_path:
        local = profile_local_ok(profile, local)  # --model-path still lets you pick anything
    max_mb = None if args.budget_mb is not None else DEMO_MAX_MB
    catalog = profile_catalog(profile, "main")
    # Offline / --no-download cannot fetch the catalog. If any scanned local exists,
    # pass an empty catalog so pick_model will not prefer a download over that file.
    if _offline_choice(args) and local:
        catalog = ()
    choice, entry = pick_model(gpu["budget_mb"], local, catalog=catalog,
                               prefer=args.model_path, max_mb=max_mb)
    keep = ("path", "name", "size_mb", "label", "file", "maker", "repo", "size", "sha256")
    model = {"choice": choice, **{k: entry[k] for k in entry if k in keep},
             "maker": entry.get("maker") or maker_of(entry.get("name", "")),
             "need_mb": need_mb(entry["size_mb"]), "local_found": len(local)}
    extras = []
    if gpu["backend"] != "cpu" and not args.no_extras:
        left = gpu["budget_mb"] - need_mb(entry["size_mb"])
        for extra in pick_extras(left, model, local, catalog=profile_catalog(profile, "extra"),
                                 limit=args.extras):
            extras.append({k: extra[k] for k in extra if k in keep + ("choice",)} |
                          {"need_mb": need_mb(extra["size_mb"])})
    return model, extras


def gpu_note(gpu):
    notes = []
    if gpu.get("nvidia_hidden"):
        notes.append("NVIDIA hidden (--hide-nvidia or environment)")
    elif gpu["backend"] == "vulkan" and gpu["vendor"] != "NVIDIA" and not gpu.get("nvidia_present"):
        notes.append("No NVIDIA GPU detected, using Vulkan")
    elif gpu["vendor"] == "none":
        notes.append("No usable GPU detected, using the CPU")
    if gpu.get("integrated"):
        notes.append("integrated GPU shares system memory, small model chosen")
    return "; ".join(notes)


def plan(args, runner=subprocess.run):
    """Detect everything without loading a model. Returns a dict (also --detect-only)."""
    gpu = detect_gpu(runner, only=getattr(args, "gpu", None))
    if args.budget_mb is not None:
        gpu["budget_mb"] = args.budget_mb
    gpu["note"] = gpu_note(gpu)
    profile = gpu_profile(gpu)
    if profile:
        gpu["profile"] = profile
    elif no_avx_mac_without_profile(gpu):
        # e.g. a Mac Pro 5,1 with another GPU: the official llama.cpp cannot start there, and the GPU is unverified.
        # Use the bundled no-AVX build on the CPU with a small model rather than a download that cannot run.
        was_gpu = gpu["backend"] != "cpu"
        gpu.update(backend="cpu", budget_mb=CPU_BUDGET_MB if args.budget_mb is None else args.budget_mb,
                   noavx_cpu=True)
        if was_gpu:
            gpu["note"] = (f"This Mac's CPU has no AVX and {gpu['name']} is not a GPU that GPU Link has verified on it; "
                           "using the CPU with a smaller model")
    result = {"gpu": gpu, "existing": [], "runtime": None, "model": None, "extras": []}
    if not args.own_server:
        result["existing"] = find_existing_servers(args.strict_ports, runner)
    if result["existing"] and not args.own_server:
        backend = result["existing"][0]
        result["runtime"] = {"type": "existing", "url": backend["url"], "kind": backend["kind"]}
        result["model"] = {"id": choose_server_model(backend, gpu["budget_mb"])}
        return result
    binary = find_llama_server(args.runtime_dir, gpu=gpu)
    result["runtime"] = {"type": "llama-server", "binary": str(binary) if binary else None,
                         "download": binary is None,
                         "asset": llama_asset(platform.system(), platform.machine(), gpu)[0]}
    if wants_noavx_vulkan(gpu) and pins.NOAVX_VULKAN_MACOS_X64:
        pin = pins.NOAVX_VULKAN_MACOS_X64
        ready = args.runtime_dir / pin["dir"] / "bin" / "llama-server"
        bundled = bundled_noavx_archive(pin) is not None
        result["runtime"] = {"type": "llama-server", "binary": str(ready) if ready.is_file() else None,
                             "download": False, "asset": pin["name"],
                             "source": "bundled" if bundled else ("mirror" if pin.get("url") else "missing")}
    result["model"], result["extras"] = choose_models(args, gpu, profile)
    return result


def arguments(argv=None):
    base = data_dir()
    p = argparse.ArgumentParser(description="Plug-and-play OPOS GPU Link companion")
    p.add_argument("--hide-nvidia", action="store_true",
                   help="pretend this computer has no NVIDIA GPU (tests the AMD/Intel/CPU fallback)")
    p.add_argument("--detect-only", action="store_true", help="print what would be used and exit")
    p.add_argument("--prefetch", action="store_true",
                   help="download everything needed (runtime, adb, models) and exit; do this at home")
    p.add_argument("--selftest", action="store_true", help="print platform/bundle facts and exit; loads nothing")
    p.add_argument("--e2e", action="store_true", help="headless end-to-end check with a fake phone lane")
    p.add_argument("--receipt", type=Path, help="where --e2e writes its JSON receipt")
    p.add_argument("--json", action="store_true")
    p.add_argument("--strict-ports", action="store_true",
                   help="never probe protected ports, even an LM Studio on 1234")
    p.add_argument("--own-server", action="store_true", help="ignore running servers; launch llama-server")
    p.add_argument("--port", type=int, default=DEFAULT_LAUNCH_PORT, help="first port to try for our servers")
    p.add_argument("--model-path", help="GGUF path or name fragment to prefer (may be a coder model)")
    p.add_argument("--budget-mb", type=int, help="override detected GPU memory budget")
    p.add_argument("--gpu", choices=GPU_CHOICES, default=normalize_gpu_choice(os.environ.get(GPU_ENV)),
                   help="use only this GPU vendor and hide the others (default auto, or $" + GPU_ENV + "); "
                        "'amd'/'intel' take the Vulkan path even when an NVIDIA card is present")
    p.add_argument("--extras", type=int, default=MAX_EXTRAS, choices=(0, 1, 2),
                   help="how many smaller extra computer lanes to add automatically (default 2)")
    p.add_argument("--no-extras", action="store_true", help="same as --extras 0")
    p.add_argument("--no-download", action="store_true",
                   help="do not download llama.cpp, adb or models; fail if they are missing")
    p.add_argument("--offline", action="store_true",
                   help="show-day mode: do not use the internet (sets --no-download and "
                        "refuses any download path). Frozen one-file apps default to this "
                        "unless --prefetch, --offline, or --no-download is already passed. "
                        "Use --prefetch at home first")
    p.add_argument("--adb", help="adb executable")
    p.add_argument("--serial", help="phone USB serial")
    p.add_argument("--no-phone", action="store_true",
                   help="set up the GPU models only (for testing); do not wait for a phone")
    p.add_argument("--no-pause", action="store_true", help="do not wait for Return at exit (bundles)")
    p.add_argument("--data-dir", type=Path, default=base)
    p.add_argument("--runtime-dir", type=Path)
    p.add_argument("--models-dir", type=Path)
    p.add_argument("--log-dir", type=Path)
    p.add_argument("--keep-server", action="store_true", help="leave our llama-server running on exit")
    args, rest = p.parse_known_args(argv)
    incoming = list(argv) if argv is not None else list(sys.argv[1:])
    if should_default_offline(incoming):
        args.offline = True
    if args.offline or is_offline():
        if args.prefetch:
            p.error("--offline and --prefetch cannot be used together; "
                    "run --prefetch at home, then start with --offline at the venue")
        args.offline = True
        args.no_download = True
        os.environ[OFFLINE_ENV] = "1"
    args.runtime_dir = args.runtime_dir or args.data_dir / "runtime"
    args.models_dir = args.models_dir or args.data_dir / "models"
    args.log_dir = args.log_dir or args.data_dir / "logs"
    args.companion_args = rest
    return args


class Runtime:
    """What start_runtime brought up: lanes[0] is the lead model."""

    def __init__(self):
        self.lanes, self.servers, self.key, self.key_file = [], [], None, None
        self.on_gpu, self.evidence, self.existing, self.device = None, [], False, None
        self.lock = threading.RLock()
        self.state_lock = threading.RLock()
        self.stopping = threading.Event()
        self.supervisor = self.watchdog = self.fallback_plan = None
        self.launches, self.models, self.catalog_entries = {}, {}, {}
        self.failure_attempts, self.fallback_threads, self.callbacks = set(), [], []
        self.failed_children = []
        self.pending = set()
        self.crashes, self.revision = {}, 0

    def stop_supervision(self):
        self.stopping.set()
        with self.state_lock:
            threads = [self.supervisor, *self.fallback_threads]
        for thread in threads:
            if thread is not None and thread is not threading.current_thread():
                thread.join()

    def listen(self, callback):
        with self.state_lock:
            self.callbacks.append(callback)

    def unlisten(self, callback):
        with self.state_lock:
            if callback in self.callbacks:
                self.callbacks.remove(callback)

    def _notify(self, event):
        # Events contain only slot/status/revision, never argv, env, key or text.
        for callback in tuple(self.callbacks):
            try:
                callback(dict(event))
            except Exception:
                pass

    def lane(self, lane_id):
        with self.state_lock:
            return next((dict(lane) for lane in self.lanes if lane["id"] == lane_id), None)

    def _watch_event(self, event):
        if event["status"] in {"restart_pending", "restarted", "gave_up", "port_busy", "ownership_refused"}:
            alias = self.launches[event["port"]]["alias"]
            if event["status"] == "restart_pending":
                self.crashes[alias] = self.crashes.get(alias, 0) + 1
            self._notify({"lane": alias, "status": event["status"], "revision": self.revision})

    def _restart_owned(self, argv, **_options):
        port = int(argv[argv.index("--port") + 1])
        record = self.launches.get(port)
        if (self.existing or self.stopping.is_set() or record is None
                or port in LAUNCH_FORBIDDEN or tuple(argv) != record["argv"]
                or not any(s.port == port and self._owns(s, record) for s in self.servers)):
            raise ValueError("Restart requires our recorded slot and command")
        key_file = write_key_file(self.key)
        command = list(record["argv"])
        command[command.index("--api-key-file") + 1] = str(key_file)
        process = child_pid = None
        try:
            with record["log_path"].open("ab") as log:
                process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                           env=record["env"], **record["options"])
                child_pid = process.pid
            child = LaunchedServer(process, port, record["log_path"], record["alias"])
            if not wait_healthy(child, cancelled=self.stopping.is_set):
                raise OSError("Owned model restart did not become ready")
            # The watchdog replays the canonical recorded argv, not the expired
            # temporary credential pathname used by this individual child.
            process.args = list(record["argv"])
            record["process"] = process
            record["pid"] = process.pid
            return process
        except BaseException:
            if process is not None:
                self._cleanup_child(LaunchedServer(process, port, record["log_path"], record["alias"]), child_pid)
            raise
        finally:
            shutil.rmtree(key_file.parent, ignore_errors=True)

    def _cleanup_child(self, server, pid):
        """Retain failed cleanup ownership so shutdown can try again safely."""
        record = {"process": server.process, "pid": pid, "alias": server.alias}
        if not self._owns(server, record):
            self._notify({"lane": server.alias, "status": "ownership_refused", "revision": self.revision})
            return
        try:
            server.stop(quiet=True)
        except (OSError, subprocess.SubprocessError):
            with self.state_lock:
                self.failed_children.append((server, record))
            self._notify({"lane": server.alias, "status": "cleanup_failed", "revision": self.revision})

    def start_guards(self, args, gpu):
        if self.existing or FallbackPlan is None:
            return
        if not any(isinstance(getattr(server, "launch", None), dict) for server in self.servers):
            return
        self.args, self.gpu = args, dict(gpu)
        available = []
        rows = [*(profile_catalog(gpu.get("profile"), "main") or
                  tuple(catalog_entry(row) for row in pins.MODELS if row["role"] == "main")),
                *(profile_catalog(gpu.get("profile"), "extra") or
                  tuple(catalog_entry(row) for row in pins.MODELS if row["role"] == "extra"))]
        local = scan_local_ggufs([args.models_dir, *model_dirs(here=args.data_dir)])
        paths = {Path(entry["path"]).name: Path(entry["path"]) for entry in local}
        catalog = []
        for row in rows:
            path = paths.get(row["file"], args.models_dir / row["file"])
            good = (path.is_file() and path.stat().st_size == row["size"]
                    and verified_file(path, row["sha256"]))
            model = Model(row["label"], row["size"], path if good else None,
                          sha256=row["sha256"], available=good)
            self.catalog_entries[model.name] = row
            (available if good else catalog).append(model)
        for server, lane in zip(self.servers, self.lanes):
            record = getattr(server, "launch", None)
            if not isinstance(record, dict):  # A partial/legacy launcher cannot be supervised.
                continue
            self.launches[server.port] = record
            self.models[lane["id"]] = Model(lane["label"], record["size"], record["model_path"],
                                             known_good=False, available=True)
        self.fallback_plan = FallbackPlan(available, catalog,
                                         offline=args.no_download or is_offline())
        if self.launches and Watchdog is not None and watchdog_enabled():
            self.watchdog = Watchdog(self, process_factory=self._restart_owned,
                                     allowed_ports=frozenset(self.launches),
                                     spawn_options={port: dict(row["options"], env=row["env"])
                                                    for port, row in self.launches.items()},
                                     notify=self._watch_event)
            def supervise():
                while not self.stopping.wait(1):
                    try:
                        with self.lock:
                            self.watchdog.tick()
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError):
                        self._notify({"status": "supervisor_error", "revision": self.revision})
            self.supervisor = threading.Thread(target=supervise, name="opos-model-watchdog", daemon=True)
            self.supervisor.start()

    @staticmethod
    def _owns(server, record):
        return (server.process is record["process"] and server.process.pid == record["pid"]
                and isinstance(server.process.pid, int) and server.process.pid > 0
                and server.process.pid not in PROTECTED_PIDS)

    def record_failure(self, lane_id, job, reason):
        with self.state_lock:
            if self.stopping.is_set() or self.fallback_plan is None or lane_id not in self.models:
                return None
            attempt = lane_id, job.get("lease"), job["question"]
            if attempt in self.failure_attempts:
                return self.fallback_plan.status(lane_id)
            self.failure_attempts.add(attempt)
            offer = self.fallback_plan.record_failure(lane_id, job["question"], self.models[lane_id], reason)
            if offer is not None:
                candidate, _label = offer
                self.pending.add(lane_id)
                thread = threading.Thread(target=self._fallback, args=(lane_id, job["question"], candidate),
                                          name="opos-model-fallback", daemon=True)
                self.fallback_threads.append(thread)
                thread.start()
            return self.fallback_plan.status(lane_id)

    def _fallback(self, lane_id, question, candidate):
        if self.stopping.is_set():
            with self.state_lock:
                self.pending.discard(lane_id)
            return
        key_file = new_server = new_pid = None
        try:
            with self.lock:
                server = next(s for s in self.servers if s.alias == lane_id)
                old = self.launches[server.port]
                original = self.models[lane_id]
                if not self._owns(server, old):
                    raise ValueError("Refusing an unowned fallback target")
                # Release the slot before slow work; other watchdog slots and
                # phone lane readers continue while this one recovers.
                if self.watchdog is not None:
                    self.watchdog.release(server)
            row = self.catalog_entries[candidate.name]
            allow_download = not (self.args.no_download or is_offline())
            path = candidate.path
            if path is None:
                path, _ = ensure_model("download", row, self.args.models_dir, allow_download)
            if (not path.is_file() or path.stat().st_size != candidate.size
                    or not verified_file(path, candidate.sha256)):
                raise RuntimeError("Fallback file is missing or unverified")
            if self.stopping.is_set():
                raise RuntimeError("Runtime stopping")
            server.stop(quiet=True)
            from gpu_link_health import port_available
            if not port_available(server.port, allowed_ports=frozenset(self.launches)):
                raise RuntimeError("Owned fallback port unavailable")
            key_file = write_key_file(self.key)
            command = server_command(old["argv"][0], path, server.port, key_file, lane_id,
                                     old["backend"], old["ctx"], old["profile"], old["device"])
            with old["log_path"].open("ab") as log:
                child = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT,
                                         env=old["env"], **old["options"])
                new_pid = child.pid
            new_server = LaunchedServer(child, server.port, old["log_path"], lane_id)
            if not wait_healthy(new_server, cancelled=self.stopping.is_set):
                raise RuntimeError("Fallback model did not become ready")
            if self.stopping.is_set():
                raise RuntimeError("Runtime stopping")
            canonical = list(command)
            canonical[canonical.index("--api-key-file") + 1] = old["argv"][old["argv"].index("--api-key-file") + 1]
            child.args = canonical
            record = dict(old, argv=tuple(canonical), model_path=path, size=candidate.size,
                          process=child, pid=child.pid)
            with self.lock:
                server.process, server.launch = child, record
                self.launches[server.port] = record
                if self.watchdog is not None:
                    self.watchdog.adopt(server, dict(record["options"], env=record["env"]))
            with self.state_lock:
                self.models[lane_id] = candidate
                lane = next(lane for lane in self.lanes if lane["id"] == lane_id)
                lane.update(label=f"{candidate.name[:23]} (fallback for {original.name[:23]})",
                            maker=maker_of(candidate.name), size_mb=candidate.size >> 20, on_gpu=None)
                if self.lanes[0]["id"] == lane_id:
                    lane["lead_label"] = lane["label"]
                    self.on_gpu, self.evidence = None, ["fallback GPU use not measured"]
                self.revision += 1
            self._notify({"lane": lane_id, "status": "fallback", "revision": self.revision})
        except (OSError, ValueError, RuntimeError, KeyError, StopIteration, subprocess.SubprocessError):
            if new_server is not None:
                self._cleanup_child(new_server, new_pid)
            self.fallback_plan.record_failure(lane_id, question, candidate, "model_start")
            self._notify({"lane": lane_id, "status": "fallback_failed", "revision": self.revision})
        finally:
            if key_file is not None:
                shutil.rmtree(key_file.parent, ignore_errors=True)
            with self.state_lock:
                self.pending.discard(lane_id)

    def stop(self):
        self.stop_supervision()
        failure = None
        children = [(server, self.launches.get(server.port)) for server in reversed(self.servers)]
        children.extend(self.failed_children)
        remaining, seen = [], set()
        for server, record in children:
            if id(server.process) in seen:
                continue
            seen.add(id(server.process))
            if record is not None and not self._owns(server, record):
                self._notify({"lane": record["alias"], "status": "ownership_refused", "revision": self.revision})
                continue
            try:
                server.stop()
            except (OSError, subprocess.SubprocessError) as error:
                failure = error
                remaining.append((server, record or {"process": server.process, "pid": server.process.pid,
                                                     "alias": server.alias}))
        self.servers = []
        self.failed_children = remaining
        self.drop_key_file()
        self.key = None
        if failure is not None:
            raise failure

    def drop_key_file(self):
        if self.key_file is not None:
            shutil.rmtree(self.key_file.parent, ignore_errors=True)
            self.key_file = None


def fetch_plan(args, info):
    """Download (checked) everything the plan needs. Returns local paths per lane."""
    allow = not args.no_download
    gpu = info["gpu"]
    out = {"adb": None, "binary": None, "models": []}
    if info["runtime"]["type"] == "llama-server":
        out["binary"] = ensure_llama_server(args.runtime_dir, gpu, allow_download=allow)
        for entry in [info["model"], *info["extras"]]:
            out["models"].append(ensure_model(entry["choice"], entry, args.models_dir, allow))
    out["adb"] = ensure_adb(args.runtime_dir, args.adb, allow)
    return out


def looks_like_text(text: str) -> bool:
    """True when a reply holds real words (a broken GPU backend can return blank or junk)."""
    words = re.findall(r"[A-Za-z]{2,}", re.sub(r"<[^>\s]*>", " ", text or ""))
    return len(words) >= 2


def check_lane_output(port: int, key: str, alias: str = ALIAS, timeout=60):
    """Ask the lane for a few words. Returns (ok, detail). Catches GPU backends that
    load and run fast but return empty text (seen: Gemma 3 on an RX 580 via MoltenVK)."""
    import http.client
    body = json.dumps({"model": alias, "max_tokens": 48, "temperature": 0, "stream": False,
                       "messages": [{"role": "user", "content": "Say hello to the audience in one short sentence."}]})
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("POST", "/v1/chat/completions", body,
                     {"Content-Type": "application/json", "Authorization": "Bearer " + key})
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        if response.status != 200:
            return False, f"HTTP {response.status}"
        message = json.loads(raw)["choices"][0]["message"]
        text = (message.get("content") or "") + " " + (message.get("reasoning_content") or "")
    except (OSError, ValueError, KeyError, IndexError) as error:
        return False, f"{type(error).__name__}"
    return (True, "ok") if looks_like_text(text) else (False, "the reply had no readable words")


def start_runtime(args, info, runner=subprocess.run):
    """Bring up the model server(s). Returns a Runtime (lanes[0] = lead model)."""
    gpu = info["gpu"]
    rt = Runtime()
    if info["runtime"]["type"] == "existing":
        url = gpu_link_discover.chat_url(info["runtime"]["url"])
        say(f"Using the model server already running here: {info['runtime']['kind']} at {url}")
        rt.existing = True
        model = info["model"]
        served = served_model_label(model.get("label"), model.get("id"))
        if not served:
            raise RuntimeError("Existing server has no usable model label")
        rt.lanes = [{"id": model.get("id") or "opos-gpu-link", "url": url, "label": served,
                     "maker": "Local", "lead_label": served}]
        rt.evidence = ["existing server; GPU use not measured"]
        return rt
    binary = ensure_llama_server(args.runtime_dir, gpu, allow_download=not args.no_download)
    profile = gpu.get("profile")
    env = runtime_env(binary)
    if profile == PROFILE_RX580:
        env = moltenvk_env(env, binary=binary)
    hidden = hide_nvidia() or gpu.get("nvidia_hidden", False)
    if hidden:
        env = hide_nvidia_env(env)
    ok, detail = probe_binary(binary, env, runner)
    if not ok:
        hint = "" if cpu_has_avx() else " This CPU has no AVX."
        raise RuntimeError(f"llama-server cannot run on this computer: {detail}.{hint} "
                           "Set OPOS_LLAMA_SERVER to a llama.cpp build made for this computer "
                           "(see PLUG-AND-PLAY.md, 'Old computers').")
    devices = classify_devices(list_devices(binary, env, runner), hidden) if gpu["backend"] != "cpu" else []
    device = None
    if gpu["backend"] != "cpu" and not devices:
        message = (f"No usable GPU backend found for {gpu['name']}. "
                   "Running on the CPU with a smaller model (answers will be slower)")
        banner([message])
        override = getattr(args, "budget_mb", None)
        note = message
        if hidden:
            note = "NVIDIA hidden (--hide-nvidia or environment). " + note
        gpu = info["gpu"] = dict(gpu, backend="cpu", budget_mb=CPU_BUDGET_MB if override is None else override,
                                 note=note)
        info["model"], info["extras"] = choose_models(args, gpu, profile)
    else:
        device = pick_vulkan_device(devices, gpu)
        rt.device = device
        if device:
            say(f"Several Vulkan GPUs found; using {device} for {gpu['name']}.")
        elif gpu["backend"] == "vulkan" and sum(1 for d in devices if d.startswith("Vulkan")) > 1:
            if gpu.get("forced"):
                raise RuntimeError(f"--gpu {gpu['forced']}: several Vulkan GPUs found and none matched {gpu['name']}, "
                                   "so llama.cpp could use the wrong one. Not starting. Use --gpu auto, or hide "
                                   "the other GPU.")
            banner([f"WARNING: several Vulkan GPUs found and none matched {gpu['name']}.",
                    "llama.cpp will use its default GPU, which may not be the one you chose."])
        if gpu["backend"] == "vulkan" and devices:
            visible_nvidia = (gpu["vendor"] == "NVIDIA" or gpu.get("nvidia_present")
                              or any(CUDA_DEVICE.match(line) or NVIDIA_NAME.search(line) for line in devices))
            if hidden or not visible_nvidia:
                vulkan = next((line for line in devices if line.startswith("Vulkan")), None)
                if vulkan:
                    name = re.sub(r"\s*\(\d+ MiB.*\)$", "", vulkan.partition(":")[2].strip())
                    say(f"No NVIDIA GPU: using {name} through Vulkan (about {gpu['budget_mb']} MB usable)")
    rt.key = new_key()
    rt.key_file = write_key_file(rt.key)
    os.environ[KEY_ENV] = rt.key  # for the companion in this process only
    lanes = [info["model"], *info["extras"]]
    taken = []
    try:
        for index, entry in enumerate(lanes):
            model_path, label = ensure_model(entry["choice"], entry, args.models_dir, not args.no_download)
            port = choose_port(args.port, taken=taken)
            taken.append(port)
            alias = ALIAS if index == 0 else f"{ALIAS}-{index + 1}"
            target = "the CPU" if gpu["backend"] == "cpu" else gpu["name"]
            say(f"Loading {label} on {target} (port {port}) ...")
            used_before = vram_used_mb(gpu, runner) if gpu["backend"] != "cpu" else None
            server = launch_llama_server(binary, model_path, port, env, args.log_dir, gpu["backend"],
                                         rt.key_file, alias, profile=profile, device=device)
            rt.servers.append(server)
            if not wait_healthy(server):
                if index == 0:
                    raise RuntimeError(f"llama-server did not become ready; see {server.log_path}")
                say(f"Extra model {label} did not start; continuing without it.")
                server.stop(quiet=True)
                rt.servers.pop()
                continue
            on_gpu, evidence = verify_gpu(server, gpu, runner, devices, used_before=used_before)
            if devices and index == 0:
                evidence.insert(0, "devices: " + "; ".join(devices))
            if index == 0:
                rt.on_gpu, rt.evidence = on_gpu, evidence
            gpu_output_bad = False
            if on_gpu and gpu["backend"] != "cpu":
                good, why = check_lane_output(port, rt.key, alias)
                if not good:
                    gpu_output_bad = True
                    banner([f"The GPU gave unusable output for {label} ({why}).",
                            "Falling back to the CPU for this model (slower, but it answers).",
                            "This is a driver/backend problem, not a setup problem."])
                    server.stop(quiet=True)
                    rt.servers.pop()
                    server = launch_llama_server(binary, model_path, port, env, args.log_dir, "cpu",
                                                 rt.key_file, alias, profile=profile)
                    rt.servers.append(server)
                    if not wait_healthy(server):
                        raise RuntimeError(f"llama-server (CPU fallback) did not become ready; see {server.log_path}")
                    on_gpu, evidence = False, evidence + ["GPU output was blank; this lane runs on the CPU instead"]
                    if index == 0:
                        rt.on_gpu, rt.evidence = on_gpu, evidence
            if on_gpu:
                say(f"{label} is on the GPU: " + " | ".join(evidence))
            elif gpu_output_bad:
                say(f"{label} is on the CPU (the GPU backend returned blank text).")
            elif gpu["backend"] != "cpu":
                banner([f"RUNNING ON CPU - the GPU is NOT being used for {label}.", *evidence,
                        f"Log: {server.log_path}"])
            served = served_model_label(label, entry.get("name")) or alias
            lane = {"id": alias, "url": f"{server.base_url}/v1/chat/completions", "label": served,
                    "maker": (entry.get("maker") or maker_of(entry.get("name", "")))[:32],
                    "on_gpu": on_gpu, "gpu_output_bad": gpu_output_bad, "port": port, "size_mb": entry["size_mb"]}
            if index == 0:
                lane["lead_label"] = served
            rt.lanes.append(lane)
    except BaseException:
        rt.stop()
        os.environ.pop(KEY_ENV, None)
        raise
    try:
        rt.start_guards(args, gpu)
    except BaseException:
        rt.stop()
        os.environ.pop(KEY_ENV, None)
        raise
    rt.drop_key_file()  # servers have read it; nothing on disk keeps the key
    return rt


def companion_args(args, rt, info, adb, serial):
    lead = rt.lanes[0]
    argv = ["--headless", "--always-allow", "--adb", str(adb), "--serial", serial,
            "--server", lead["url"], "--model", lead["id"], "--label", safe_label(info["gpu"]),
            *protected_flags(lead["url"])]
    for lane in rt.lanes[1:]:
        argv += ["--extra-model", f"{lane['id']}:{lane['label'].replace(':', ' ')}:{lane['maker'].replace(':', ' ')}",
                 "--model-server", f"{lane['id']}={lane['url']}"]
    return argv + list(args.companion_args)


def print_detect(info, as_json=False):
    if as_json:
        print(json.dumps(info, default=str))
        return
    g = info["gpu"]
    say(f"GPU: {g['name']} ({g['vendor']}, backend {g['backend']}, budget {g['budget_mb']} MB"
        + (f", profile {g['profile']}" if g.get("profile") else "") + ")")
    if g.get("note"):
        say(g["note"])
    say(f"Runtime: {json.dumps(info['runtime'])}")
    say(f"Model: {json.dumps(info['model'])}")
    for extra in info.get("extras", []):
        say(f"Extra: {json.dumps(extra)}")


def selftest() -> int:
    bundled_adb = RESOURCES / "bundled" / "adb" / _exe("adb")
    facts = {"frozen": FROZEN, "python": platform.python_version(), "os": platform.platform(),
             "machine": platform.machine(), "data_dir": str(data_dir()),
             "bundled_adb": str(bundled_adb) if bundled_adb.is_file() else None,
             "bundled_llama": None, "pinned_llama_tag": LLAMA_TAG, "avx": cpu_has_avx(),
             "gpu_hidden_nvidia": hide_nvidia()}
    if bundled_adb.is_file():
        ensure_exec(bundled_adb)
        facts["bundled_adb_version"] = (_run([str(bundled_adb), "version"]) or "").splitlines()[:1]
    llama = find_llama_server(Path("/nonexistent"), which=lambda _: None)
    if llama:
        facts["bundled_llama"] = str(llama)
        env = runtime_env(llama)
        if facts["gpu_hidden_nvidia"]:
            env = hide_nvidia_env(env)
        facts["bundled_llama_probe"] = probe_binary(llama, env)
    pin = pins.NOAVX_VULKAN_MACOS_X64
    if pin:
        archive = bundled_noavx_archive(pin)
        facts["bundled_noavx_vulkan"] = {"name": pin["name"], "present": archive is not None,
                                         "sha256_ok": archive is not None and sha256_file(archive) == pin["sha256"]}
    facts["bundled_llama_archives"] = bundled_llama_archive_facts()
    gpu = detect_gpu()
    facts["gpu"] = {k: gpu.get(k) for k in ("vendor", "name", "backend", "budget_mb", "driver_faked") if k in gpu}
    print(json.dumps(facts, indent=2, default=str))
    return 0


def pause_if_interactive(args, code):
    if FROZEN and not args.no_pause and not args.companion_args and sys.stdin and sys.stdin.isatty():
        try:
            input(f"\nGPU Link stopped (code {code}). Press Return to close this window.")
        except (EOFError, KeyboardInterrupt):
            pass


def main(argv=None) -> int:
    args = arguments(argv)
    if args.hide_nvidia:
        os.environ["OPOS_GPU_LINK_HIDE_NVIDIA"] = "1"
    if args.selftest:
        return selftest()
    if args.e2e:
        import gpu_link_e2e
        return gpu_link_e2e.run(args)
    code = run(args)
    pause_if_interactive(args, code)
    return code


def run(args) -> int:
    info = plan(args)
    if args.detect_only:
        print_detect(info, args.json)
        return 0
    if args.prefetch:
        try:
            got = fetch_plan(args, info)
        except RuntimeError as error:
            say("Prefetch stopped: " + str(error))
            return 2
        print_detect(info)
        total = sum(Path(p).stat().st_size for p, _ in got["models"]) if got["models"] else 0
        say(f"Prefetch complete: runtime {got['binary']}, adb {got['adb']}, "
            f"{len(got['models'])} model file(s), {total >> 20} MB of models. Everything is SHA-256 verified.")
        return 0
    rt = None
    try:
        rt = start_runtime(args, info)
        if args.no_phone:
            say("Model server(s) ready; --no-phone given, not starting the phone link. Ctrl-C to stop.")
            stop = threading.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda *_: stop.set())
            stop.wait()
            return 0
        adb = ensure_adb(args.runtime_dir, args.adb, not args.no_download)
        say(f"adb: {adb}")
        serial = args.serial or wait_for_phone(adb)
        import opos_gpu_link
        banner(ready_lines(info["gpu"]["name"], rt.lanes, opos_gpu_link.computer_noun()))
        return opos_gpu_link.main(companion_args(args, rt, info, adb, serial), runtime=rt)
    except KeyboardInterrupt:
        return 130
    except RuntimeError as error:
        say("Setup stopped: " + str(error))
        return 2
    finally:
        if rt is not None:
            if args.keep_server:
                rt.stop_supervision()
                rt.drop_key_file()
                rt.key = None
            else:
                rt.stop()
            os.environ.pop(KEY_ENV, None)


if __name__ == "__main__":
    raise SystemExit(main())

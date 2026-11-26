# SPDX-License-Identifier: Apache-2.0
"""Build one self-contained executable with PyInstaller (run on the target OS).

  python build_bundle.py            # adb inside; llama.cpp inside on Apple Silicon (Metal),
                                    # and Windows/Linux carry pinned CUDA + Vulkan archives
  python build_bundle.py --with-llama   # also extract llama.cpp for this OS/GPU into bundled/llama
                                    # (large for CUDA; Windows/Linux already pack archives)
  python build_bundle.py --no-adb   # leave adb out; the app then uses the adb the user installed
                                    # (Google's Android SDK Platform-Tools), as for public releases

adb (and llama.cpp) are fetched from the pinned, SHA-256-checked URLs in gpu_link_pins.
macOS: the result is ad-hoc signed only (no Developer ID, no notarization).
"""
import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gpu_link_autosetup as a  # noqa: E402


def stage_adb(system, cache, work, stage):
    """Copy the pinned platform-tools adb (plus the Windows DLLs) into stage/adb."""
    os_name = {"Darwin": "darwin", "Linux": "linux", "Windows": "windows"}[system]
    pin = a.pins.PLATFORM_TOOLS[os_name]
    zip_path = a.download(pin["url"], cache / f"platform-tools-{os_name}.zip", "platform-tools", pin["sha256"], pin["size"])
    tools = work / "pt"
    a.extract(zip_path, tools)
    (stage / "adb").mkdir(parents=True)
    exe = "adb.exe" if system == "Windows" else "adb"
    shutil.copy2(tools / "platform-tools" / exe, stage / "adb" / exe)
    if system == "Windows":
        for dll in ("AdbWinApi.dll", "AdbWinUsbApi.dll"):
            shutil.copy2(tools / "platform-tools" / dll, stage / "adb" / dll)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--with-llama", action="store_true")
    p.add_argument("--no-adb", action="store_true",
                   help="do not pack adb; users install Google's Android SDK Platform-Tools themselves")
    p.add_argument("--noavx-vulkan", type=Path,
                   help="Darwin x86_64 only: the pinned no-AVX Vulkan/MoltenVK llama.cpp .tar.gz made by "
                        "pack_noavx_vulkan.py (default: build-cache/<pinned name>)")
    p.add_argument("--out", type=Path, default=HERE.parent / "bundles")
    p.add_argument("--name", default="opos-gpu-link")
    args = p.parse_args(argv)
    system, machine = platform.system(), platform.machine()
    work = HERE.parent / "build-work" / f"{system}-{machine}"
    shutil.rmtree(work, ignore_errors=True)
    stage = work / "bundled"
    cache = HERE.parent / "build-cache"
    stage.mkdir(parents=True)
    if args.no_adb:
        print("adb: not bundled (--no-adb)")
    else:
        stage_adb(system, cache, work, stage)
    if args.with_llama or (system == "Darwin" and machine == "arm64"):
        gpu = a.detect_gpu()
        suffix, cudart = a.llama_asset(system, machine, gpu)
        names = [f"llama-{a.LLAMA_TAG}-bin-{suffix}"] + ([cudart.format(tag=a.LLAMA_TAG)] if cudart else [])
        for name in names:
            lp = a.pins.LLAMA[name]
            arc = a.download(a.GITHUB_RELEASE.format(tag=a.LLAMA_TAG, name=name), cache / name, name, lp["sha256"], lp["size"])
            a.extract(arc, stage / "llama")
    pin = a.pins.NOAVX_VULKAN_MACOS_X64
    if pin and system == "Darwin" and machine.lower() in ("x86_64", "amd64"):
        archive = args.noavx_vulkan or cache / pin["name"]
        if not archive.is_file():
            sys.exit(f"missing {archive}: this Darwin x86_64 bundle must carry the pinned no-AVX Vulkan runtime "
                     f"(see PLUG-AND-PLAY.md, 'Intel Mac without AVX')")
        if a.sha256_file(archive) != pin["sha256"]:
            sys.exit(f"{archive}: SHA-256 does not match the pin in gpu_link_pins.py; not bundled")
        shutil.copy2(archive, stage / pin["name"])
        print("bundled", pin["name"], pin["sha256"])
    # Windows and Linux: pack pinned CUDA + Vulkan archives (extracted on first start,
    # matching the GPU). Windows CUDA 12.4 is omitted to keep the size from doubling.
    for name in a.official_bundle_llama_archives(system, machine):
        lp = a.pins.LLAMA[name]
        dest = stage / "llama-archives"
        dest.mkdir(parents=True, exist_ok=True)
        arc = a.download(a.GITHUB_RELEASE.format(tag=a.LLAMA_TAG, name=name), cache / name, name, lp["sha256"], lp["size"])
        shutil.copy2(arc, dest / name)
        print("bundled", name, lp["sha256"], lp["size"], "bytes")
    sep = ";" if system == "Windows" else ":"
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile", "--console",
           "--name", args.name, "--distpath", str(args.out / f"{system}-{machine}"),
           "--workpath", str(work / "pyi"), "--specpath", str(work),
           "--paths", str(HERE), "--paths", str(HERE / "src"),
           "--hidden-import", "gpu_link_e2e", "--hidden-import", "opos_gpu_link",
           "--hidden-import", "gpu_link_worker", "--hidden-import", "gpu_link_discover",
           "--hidden-import", "gpu_link_guard",
           "--hidden-import", "gpu_link_health", "--hidden-import", "gpu_link_gen",
           "--hidden-import", "gpu_link_validate",
           "--hidden-import", "gpu_link_pins", "--hidden-import", "opos.gpu_link_proto",
           "--exclude-module", "tkinter", "--exclude-module", "_tkinter",
           "--add-data", f"{stage}{sep}bundled",
           "--add-data", f"{HERE / 'demo_system_prompt.txt'}{sep}.",
           "--add-data", f"{HERE / 'demo_prompts.json'}{sep}.",
           str(HERE / "gpu_link_autosetup.py")]
    subprocess.run(cmd, check=True)
    binary = args.out / f"{system}-{machine}" / (args.name + (".exe" if system == "Windows" else ""))
    if system == "Darwin":
        subprocess.run(["codesign", "--force", "--sign", "-", str(binary)], check=True)
        print(subprocess.run(["codesign", "-dv", str(binary)], stderr=subprocess.PIPE).stderr.decode())
    print("BUILT", binary, binary.stat().st_size, "bytes")


if __name__ == "__main__":
    main()

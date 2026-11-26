# SPDX-License-Identifier: Apache-2.0
"""Repackage an existing no-AVX Vulkan llama.cpp build for Intel Macs into a relocatable, pinned artifact.

Run once on the Intel Mac that built llama.cpp (macOS only: install_name_tool and codesign):

  python pack_noavx_vulkan.py --build ~/src/llama.cpp/build-vulkan/bin --sdk ~/VulkanSDK/macOS \\
      --llama-src ~/src/llama.cpp --out ~/gpulink-macpro-zero-setup/artifact

It COPIES files (the source build, which a running server may be using, is never modified), rewrites the
loader paths to be relative (@loader_path), adds MoltenVK and the Vulkan loader from the SDK, ad-hoc signs,
and writes one deterministic .tar.gz plus its SHA-256 and a MANIFEST.json (sha256 of every file in it).
Paste the printed pin into gpu_link_pins.NOAVX_VULKAN_MACOS_X64 and hand the .tar.gz to build_bundle.py
(--noavx-vulkan). Why this layout: see PLUG-AND-PLAY.md, "Intel Mac without AVX".
"""
import argparse
import gzip
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

# (file name to ship, file name in the build dir) - the install names the binaries ask for.
BIN_FILES = {
    "llama-server": "llama-server",
    "libllama-server-impl.dylib": "libllama-server-impl.dylib",
    "libllama-common.0.dylib": "libllama-common.0.8.0.dylib",
    "libmtmd.0.dylib": "libmtmd.0.8.0.dylib",
    "libllama.0.dylib": "libllama.0.8.0.dylib",
    "libggml.0.dylib": "libggml.0.28.0.dylib",
    "libggml-base.0.dylib": "libggml-base.0.28.0.dylib",
    "libggml-cpu.0.dylib": "libggml-cpu.0.28.0.dylib",
    "libggml-vulkan.0.dylib": "libggml-vulkan.0.28.0.dylib",
}
LIB_FILES = {"libvulkan.1.dylib": "libvulkan.1.dylib", "libMoltenVK.dylib": "libMoltenVK.dylib"}
ICD = {"file_format_version": "1.0.0",
       "ICD": {"library_path": "../../../lib/libMoltenVK.dylib", "api_version": "1.2.0", "is_portability_driver": True}}
PREFIX = "llama-{commit}-macos-x64-vulkan-noavx"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(*cmd):
    subprocess.run([str(c) for c in cmd], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def rpaths(path: Path):
    out = subprocess.run(["otool", "-l", str(path)], check=True, capture_output=True, text=True).stdout.splitlines()
    return [line.split("path ", 1)[1].rsplit(" (offset", 1)[0] for line in out if line.strip().startswith("path ")]


def fix_loader_paths(path: Path, rpath_list):
    for old in rpaths(path):
        run("install_name_tool", "-delete_rpath", old, path)
    for new in rpath_list:
        run("install_name_tool", "-add_rpath", new, path)
    run("codesign", "--force", "--sign", "-", path)


def tar_bytes(root: Path, prefix: str) -> bytes:
    """Deterministic tar.gz: sorted names, mtime 0, root owner, no gzip timestamp."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as t:
        for path in sorted(root.rglob("*")):
            info = t.gettarinfo(str(path), arcname=f"{prefix}/{path.relative_to(root).as_posix()}")
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            info.pax_headers = {}
            if path.is_file():
                info.mode = 0o755 if os.access(path, os.X_OK) else 0o644
                with open(path, "rb") as f:
                    t.addfile(info, f)
            else:
                info.mode = 0o755
                t.addfile(info)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0, compresslevel=9) as z:
        z.write(raw.getvalue())
    return out.getvalue()


def write_pin(pins_file: Path, pin: dict):
    """Replace the NOAVX_VULKAN_MACOS_X64 assignment in gpu_link_pins.py (it must be the last statement)."""
    text = pins_file.read_text()
    marker = "NOAVX_VULKAN_MACOS_X64 = "
    head = text[:text.index(marker)]
    body = {"name": pin["name"], "sha256": pin["sha256"], "size": pin["size"], "dir": pin["dir"], "url": None,
            "files": pin["files"]}
    pins_file.write_text(head + marker + json.dumps(body, indent=4, sort_keys=True).replace("null", "None") + "\n")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build", type=Path, required=True, help="llama.cpp build dir holding llama-server and its dylibs")
    p.add_argument("--sdk", type=Path, required=True, help="LunarG Vulkan SDK macOS dir (has lib/libMoltenVK.dylib)")
    p.add_argument("--llama-src", type=Path, required=True, help="llama.cpp checkout the build came from")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--pins", type=Path, help="gpu_link_pins.py to update with the new pin (else: print only)")
    args = p.parse_args(argv)
    if sys.platform != "darwin":
        sys.exit("run this on the Intel Mac")
    commit = subprocess.run(["git", "-C", str(args.llama_src), "rev-parse", "HEAD"], check=True,
                            capture_output=True, text=True).stdout.strip()
    prefix = PREFIX.format(commit=commit[:7])
    stage = args.out / "stage"
    shutil.rmtree(stage, ignore_errors=True)
    for sub in ("bin", "lib", "share/vulkan/icd.d"):
        (stage / sub).mkdir(parents=True)
    for dest, src in BIN_FILES.items():
        shutil.copy2((args.build / src).resolve(), stage / "bin" / dest)
    for dest, src in LIB_FILES.items():
        shutil.copy2((args.sdk / "lib" / src).resolve(), stage / "lib" / dest)
    (stage / "share/vulkan/icd.d/MoltenVK_icd.json").write_text(json.dumps(ICD, indent=2) + "\n")
    for f in (stage / "bin").iterdir():
        fix_loader_paths(f, ["@loader_path", "@loader_path/../lib"])
    for f in (stage / "lib").iterdir():  # MoltenVK / the loader only need system frameworks
        for old in rpaths(f):
            run("install_name_tool", "-delete_rpath", old, f)
        run("codesign", "--force", "--sign", "-", f)
    cache = (args.build.parent / "CMakeCache.txt")
    flags = {}
    if cache.is_file():
        for line in cache.read_text().splitlines():
            for key in ("GGML_AVX", "GGML_AVX2", "GGML_FMA", "GGML_F16C", "GGML_NATIVE", "GGML_SSE42",
                        "GGML_VULKAN", "GGML_METAL", "CMAKE_BUILD_TYPE", "BUILD_SHARED_LIBS"):
                if line.startswith(key + ":"):
                    flags[key] = line.split("=", 1)[1]
    (stage / "NOTICE.txt").write_text(
        "llama.cpp (MIT, https://github.com/ggml-org/llama.cpp) commit %s, built without AVX for Intel Macs.\n"
        "MoltenVK (Apache-2.0) and the Khronos Vulkan loader (Apache-2.0) from the LunarG Vulkan SDK.\n"
        "Only the loader paths were rewritten (relative) and the files ad-hoc signed; no code was changed.\n\n"
        "---- llama.cpp LICENSE ----\n%s\n" % (commit, (args.llama_src / "LICENSE").read_text()))
    manifest = {"name": prefix, "llama_cpp_commit": commit, "cmake": flags,
                "files": {f.relative_to(stage).as_posix(): sha256_file(f) for f in sorted(stage.rglob("*")) if f.is_file()}}
    (stage / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    blob = tar_bytes(stage, prefix)
    archive = args.out / f"{prefix}.tar.gz"
    archive.write_bytes(blob)
    digest = hashlib.sha256(blob).hexdigest()
    (args.out / f"{prefix}.tar.gz.sha256").write_text(f"{digest}  {archive.name}\n")
    pin = {"name": archive.name, "sha256": digest, "size": len(blob), "dir": prefix,
           "files": manifest["files"]}
    (args.out / "pin.json").write_text(json.dumps(pin, indent=2, sort_keys=True) + "\n")
    if args.pins:
        write_pin(args.pins, pin)
    print(json.dumps({k: pin[k] for k in ("name", "sha256", "size", "dir")}, indent=2))


if __name__ == "__main__":
    main()

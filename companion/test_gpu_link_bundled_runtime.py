# SPDX-License-Identifier: Apache-2.0
"""Bundled Windows/Linux llama.cpp archives: pick CUDA or Vulkan, unpack offline."""
import hashlib
import io
import os
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

import gpu_link_autosetup as a


CUDA_WIN = {"backend": "cuda", "cuda_variant": "win-cuda-13.5-x64"}
CUDA_WIN_124 = {"backend": "cuda", "cuda_variant": "win-cuda-12.4-x64"}
VULKAN_WIN = {"backend": "vulkan"}
CUDA_LINUX = {"backend": "cuda", "cuda_variant": "ubuntu-cuda-12.8-x64"}
VULKAN_LINUX = {"backend": "vulkan"}


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_zip(path: Path, files: dict[str, bytes]) -> bytes:
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return path.read_bytes()


def _write_tar(path: Path, files: dict[str, bytes]) -> bytes:
    with tarfile.open(path, "w:gz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            t.addfile(info, io.BytesIO(data))
    return path.read_bytes()


class OfficialArchiveList(unittest.TestCase):
    def test_windows_and_linux_carry_cuda_and_vulkan_but_not_cuda_12_4(self):
        win = a.official_bundle_llama_archives("Windows", "AMD64")
        self.assertEqual(win, [
            f"llama-{a.LLAMA_TAG}-bin-win-vulkan-x64.zip",
            f"llama-{a.LLAMA_TAG}-bin-win-cuda-13.5-x64.zip",
            "cudart-llama-bin-win-cuda-13.5-x64.zip",
        ])
        self.assertNotIn("12.4", "".join(win))
        linux = a.official_bundle_llama_archives("Linux", "x86_64")
        self.assertEqual(linux, [
            f"llama-{a.LLAMA_TAG}-bin-ubuntu-vulkan-x64.tar.gz",
            f"llama-{a.LLAMA_TAG}-bin-ubuntu-cuda-12.8-x64.tar.gz",
            f"cudart-llama-{a.LLAMA_TAG}-bin-ubuntu-cuda-12.8-x64.tar.gz",
        ])
        self.assertEqual(a.official_bundle_llama_archives("Darwin", "arm64"), [])
        self.assertEqual(a.official_bundle_llama_archives("Darwin", "x86_64"), [])

    def test_llama_archive_names_follow_the_gpu_plan(self):
        self.assertEqual(
            a.llama_archive_names("Windows", "AMD64", CUDA_WIN),
            [f"llama-{a.LLAMA_TAG}-bin-win-cuda-13.5-x64.zip",
             "cudart-llama-bin-win-cuda-13.5-x64.zip"])
        self.assertEqual(
            a.llama_archive_names("Windows", "AMD64", VULKAN_WIN),
            [f"llama-{a.LLAMA_TAG}-bin-win-vulkan-x64.zip"])


class BundledUnpack(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.res = self.root / "res"
        self.rt = self.root / "runtime"
        self.archives = self.res / "bundled" / "llama-archives"
        self.archives.mkdir(parents=True)
        self.server = b"fake-llama-server-bytes\n"
        self.pins = {}
        self._orig_llama = dict(a.pins.LLAMA)

    def tearDown(self):
        a.pins.LLAMA.clear()
        a.pins.LLAMA.update(self._orig_llama)
        self.tmp.cleanup()

    def _add_zip(self, name: str, files: dict[str, bytes]):
        raw = _write_zip(self.archives / name, files)
        self.pins[name] = {"sha256": _digest(raw), "size": len(raw)}
        a.pins.LLAMA[name] = self.pins[name]
        return self.archives / name

    def _add_tar(self, name: str, files: dict[str, bytes]):
        raw = _write_tar(self.archives / name, files)
        self.pins[name] = {"sha256": _digest(raw), "size": len(raw)}
        a.pins.LLAMA[name] = self.pins[name]
        return self.archives / name

    def _patch_resources(self):
        return patch.object(a, "RESOURCES", self.res)

    def test_offline_windows_cuda_unpacks_llama_and_cudart_and_skips_download(self):
        llama = f"llama-{a.LLAMA_TAG}-bin-win-cuda-13.5-x64.zip"
        cudart = "cudart-llama-bin-win-cuda-13.5-x64.zip"
        self._add_zip(llama, {"llama-server.exe": self.server})
        self._add_zip(cudart, {"cudart64_13.dll": b"cudart"})
        with self._patch_resources(), patch.object(a, "download") as dl:
            got = a.ensure_llama_server(self.rt, CUDA_WIN, "Windows", "AMD64", allow_download=False)
        dl.assert_not_called()
        self.assertEqual(got.name, "llama-server.exe")
        self.assertEqual(got.read_bytes(), self.server)
        self.assertTrue((got.parent / "cudart64_13.dll").is_file())
        self.assertIn("win-cuda-13.5-x64", str(got))

    def test_offline_windows_vulkan_is_chosen_instead_of_cuda(self):
        self._add_zip(f"llama-{a.LLAMA_TAG}-bin-win-vulkan-x64.zip", {"llama-server.exe": b"vulkan-bin"})
        self._add_zip(f"llama-{a.LLAMA_TAG}-bin-win-cuda-13.5-x64.zip", {"llama-server.exe": b"cuda-bin"})
        self._add_zip("cudart-llama-bin-win-cuda-13.5-x64.zip", {"cudart64_13.dll": b"cudart"})
        with self._patch_resources():
            got = a.ensure_llama_server(self.rt, VULKAN_WIN, "Windows", "AMD64", allow_download=False)
        self.assertEqual(got.read_bytes(), b"vulkan-bin")
        self.assertIn("win-vulkan-x64", str(got))
        self.assertFalse(any(p.name == "cudart64_13.dll" for p in self.rt.rglob("*")))

    def test_cuda_12_4_is_not_silently_served_the_13_5_bundle(self):
        self._add_zip(f"llama-{a.LLAMA_TAG}-bin-win-cuda-13.5-x64.zip", {"llama-server.exe": self.server})
        self._add_zip("cudart-llama-bin-win-cuda-13.5-x64.zip", {"cudart64_13.dll": b"cudart"})
        with self._patch_resources():
            with self.assertRaises(RuntimeError) as ctx:
                a.ensure_llama_server(self.rt, CUDA_WIN_124, "Windows", "AMD64", allow_download=False)
        self.assertIn("downloads are disabled", str(ctx.exception))
        self.assertFalse(any(self.rt.rglob("llama-server.exe")))

    def test_sha_mismatch_refuses_the_archive(self):
        name = f"llama-{a.LLAMA_TAG}-bin-win-vulkan-x64.zip"
        self._add_zip(name, {"llama-server.exe": self.server})
        a.pins.LLAMA[name] = {"sha256": "0" * 64, "size": 1}
        with self._patch_resources():
            with self.assertRaises(RuntimeError) as ctx:
                a.ensure_llama_server(self.rt, VULKAN_WIN, "Windows", "AMD64", allow_download=False)
        self.assertIn("SHA-256 mismatch", str(ctx.exception))
        self.assertFalse(any(self.rt.rglob("llama-server.exe")))

    def test_second_call_reuses_the_unpacked_tree(self):
        name = f"llama-{a.LLAMA_TAG}-bin-win-vulkan-x64.zip"
        self._add_zip(name, {"llama-server.exe": self.server})
        with self._patch_resources():
            first = a.ensure_llama_server(self.rt, VULKAN_WIN, "Windows", "AMD64", allow_download=False)
            # Remove the archive so a second unpack would fail; the unpacked tree must still win.
            (self.archives / name).unlink()
            second = a.ensure_llama_server(self.rt, VULKAN_WIN, "Windows", "AMD64", allow_download=False)
        self.assertEqual(first, second)

    def test_offline_linux_cuda_unpacks_both_tarballs(self):
        llama = f"llama-{a.LLAMA_TAG}-bin-ubuntu-cuda-12.8-x64.tar.gz"
        cudart = f"cudart-llama-{a.LLAMA_TAG}-bin-ubuntu-cuda-12.8-x64.tar.gz"
        self._add_tar(llama, {"bin/llama-server": self.server})
        self._add_tar(cudart, {"lib/libcudart.so": b"cudart"})
        with self._patch_resources(), patch.object(a, "download") as dl:
            got = a.ensure_llama_server(self.rt, CUDA_LINUX, "Linux", "x86_64", allow_download=False)
        dl.assert_not_called()
        self.assertEqual(got.name, "llama-server")
        self.assertEqual(got.read_bytes(), self.server)
        self.assertTrue((got.parent.parent / "lib" / "libcudart.so").is_file() or (got.parent / "libcudart.so").is_file()
                        or any(p.name == "libcudart.so" for p in self.rt.rglob("libcudart.so")))

    def test_facts_list_present_archives(self):
        name = f"llama-{a.LLAMA_TAG}-bin-win-vulkan-x64.zip"
        self._add_zip(name, {"llama-server.exe": self.server})
        with self._patch_resources():
            rows = a.bundled_llama_archive_facts()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], name)
        self.assertTrue(rows[0]["present"] and rows[0]["sha256_ok"])


if __name__ == "__main__":
    unittest.main()

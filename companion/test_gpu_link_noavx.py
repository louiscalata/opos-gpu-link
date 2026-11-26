# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the bundled no-AVX Vulkan/MoltenVK llama.cpp (Intel Mac, no setup). No network, GPU or Mac needed."""
import hashlib
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_link_autosetup as a  # noqa: E402
import gpu_link_pins  # noqa: E402
import pack_noavx_vulkan as pack  # noqa: E402

DIR = "llama-abc1234-macos-x64-vulkan-noavx"
FILES = {
    "bin/llama-server": b"#!/bin/sh\necho server\n",
    "bin/libllama.0.dylib": b"llama-lib",
    "bin/libggml-vulkan.0.dylib": b"vulkan-lib",
    "lib/libMoltenVK.dylib": b"moltenvk",
    "lib/libvulkan.1.dylib": b"loader",
    "share/vulkan/icd.d/MoltenVK_icd.json": b'{"ICD": {"library_path": "../../../lib/libMoltenVK.dylib"}}',
}
GPU = {"vendor": "AMD", "name": "AMD Radeon RX 580", "backend": "metal", "profile": a.PROFILE_RX580}


def make_tree(root: Path, files=FILES):
    for rel, data in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        path.chmod(0o755 if rel.startswith("bin/") else 0o644)


def make_archive(tmp: Path, files=FILES):
    """Build an artifact the way pack_noavx_vulkan does; returns (archive path, pin)."""
    stage = tmp / "stage"
    make_tree(stage, files)
    blob = pack.tar_bytes(stage, DIR)
    archive = tmp / f"{DIR}.tar.gz"
    archive.write_bytes(blob)
    pin = {"name": archive.name, "sha256": hashlib.sha256(blob).hexdigest(), "size": len(blob), "dir": DIR, "url": None,
           "files": {rel: hashlib.sha256(data).hexdigest() for rel, data in files.items()}}
    return archive, pin


class WhenToUseTheBundledRuntime(unittest.TestCase):
    def test_only_the_rx580_profile_on_an_intel_mac(self):
        self.assertTrue(a.wants_noavx_vulkan(GPU, "Darwin", "x86_64", {}))
        self.assertFalse(a.wants_noavx_vulkan(GPU, "Darwin", "arm64", {}))
        self.assertFalse(a.wants_noavx_vulkan(GPU, "Linux", "x86_64", {}))
        self.assertFalse(a.wants_noavx_vulkan(dict(GPU, profile=None), "Darwin", "x86_64", {}))
        self.assertFalse(a.wants_noavx_vulkan({"vendor": "AMD"}, "Darwin", "x86_64", {}))

    def test_an_explicit_server_path_is_never_overridden(self):
        self.assertFalse(a.wants_noavx_vulkan(GPU, "Darwin", "x86_64", {"OPOS_LLAMA_SERVER": "/mine/llama-server"}))


class UnpackThePinnedArtifact(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.archive, self.pin = make_archive(self.tmp / "build")
        self.rt = self.tmp / "data" / "runtime"

    def test_unpacks_verifies_and_returns_the_server(self):
        binary = a.ensure_noavx_vulkan(self.rt, pin=self.pin, archive=self.archive)
        self.assertEqual(binary, self.rt / DIR / "bin" / "llama-server")
        self.assertTrue(os.access(binary, os.X_OK))
        self.assertTrue(a.noavx_tree_ok(self.rt / DIR, self.pin))
        self.assertEqual([p.name for p in self.rt.iterdir()], [DIR])  # no staging left behind

    def test_second_start_needs_no_archive(self):
        a.ensure_noavx_vulkan(self.rt, pin=self.pin, archive=self.archive)
        self.assertEqual(a.ensure_noavx_vulkan(self.rt, pin=self.pin, archive=self.tmp / "gone.tar.gz"),
                         self.rt / DIR / "bin" / "llama-server")

    def test_a_modified_file_is_replaced_from_the_archive(self):
        a.ensure_noavx_vulkan(self.rt, pin=self.pin, archive=self.archive)
        (self.rt / DIR / "lib" / "libMoltenVK.dylib").write_bytes(b"evil")
        a.ensure_noavx_vulkan(self.rt, pin=self.pin, archive=self.archive)
        self.assertEqual((self.rt / DIR / "lib" / "libMoltenVK.dylib").read_bytes(), b"moltenvk")

    def test_a_modified_file_without_an_archive_is_not_used(self):
        a.ensure_noavx_vulkan(self.rt, pin=self.pin, archive=self.archive)
        (self.rt / DIR / "bin" / "libllama.0.dylib").write_bytes(b"evil")
        self.assertIsNone(a.ensure_noavx_vulkan(self.rt, pin=self.pin, archive=self.tmp / "gone.tar.gz"))

    def test_an_archive_with_the_wrong_hash_is_refused_and_nothing_is_unpacked(self):
        bad = self.tmp / "bad.tar.gz"
        bad.write_bytes(self.archive.read_bytes() + b"x")
        with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
            a.ensure_noavx_vulkan(self.rt, pin=self.pin, archive=bad)
        self.assertFalse((self.rt / DIR).exists())

    def test_files_not_on_the_pinned_list_are_refused(self):
        archive, pin = make_archive(self.tmp / "other", dict(FILES, **{"bin/extra": b"x"}))
        pin = dict(pin, files={k: v for k, v in pin["files"].items() if k != "bin/extra"} | {"bin/llama-server": "0" * 64})
        with self.assertRaisesRegex(RuntimeError, "do not match"):
            a.ensure_noavx_vulkan(self.rt, pin=pin, archive=archive)
        self.assertFalse((self.rt / DIR).exists())
        self.assertEqual(list(self.rt.iterdir()), [])  # staging removed

    def test_path_escape_in_the_archive_is_refused(self):
        evil = self.tmp / "evil.tar.gz"
        with tarfile.open(evil, "w:gz") as t:
            data = b"x"
            info = tarfile.TarInfo("../escape")
            info.size = 1
            t.addfile(info, __import__("io").BytesIO(data))
        pin = dict(self.pin, sha256=hashlib.sha256(evil.read_bytes()).hexdigest())
        with self.assertRaises(RuntimeError):
            a.ensure_noavx_vulkan(self.rt, pin=pin, archive=evil)
        self.assertFalse((self.tmp / "data" / "escape").exists())

    def test_no_pin_or_no_source_means_none_not_a_crash(self):
        with patch.object(gpu_link_pins, "NOAVX_VULKAN_MACOS_X64", None):
            self.assertIsNone(a.ensure_noavx_vulkan(self.rt))
        with patch.object(a, "bundled_noavx_archive", return_value=None):
            self.assertIsNone(a.ensure_noavx_vulkan(self.rt, pin=self.pin))

    def test_mirror_download_is_hash_checked_and_removed_after(self):
        pin = dict(self.pin, url="https://example.invalid/x.tar.gz")

        def fake(url, dest, label, sha256, size=None):
            self.assertEqual((url, sha256), (pin["url"], pin["sha256"]))
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(self.archive.read_bytes())
            return dest
        with patch.object(a, "bundled_noavx_archive", return_value=None), patch.object(a, "download", fake):
            binary = a.ensure_noavx_vulkan(self.rt, pin=pin)
            self.assertTrue(binary.is_file())
            self.assertFalse((self.rt / pin["name"]).exists())
            self.assertIsNone(a.ensure_noavx_vulkan(self.tmp / "other", allow_download=False, pin=pin))

    def test_bundled_archive_is_found_under_the_resources_dir(self):
        res = self.tmp / "res"
        (res / "bundled").mkdir(parents=True)
        (res / "bundled" / self.pin["name"]).write_bytes(self.archive.read_bytes())
        with patch.object(a, "RESOURCES", res):
            self.assertEqual(a.bundled_noavx_archive(self.pin), res / "bundled" / self.pin["name"])
            self.assertIsNone(a.bundled_noavx_archive(dict(self.pin, name="nope.tar.gz")))


class LauncherChoosesIt(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()).resolve()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, ignore_errors=True))
        self.archive, self.pin = make_archive(self.tmp / "build")
        self.rt = self.tmp / "runtime"
        res = self.tmp / "res"
        (res / "bundled").mkdir(parents=True)
        (res / "bundled" / self.pin["name"]).write_bytes(self.archive.read_bytes())
        for p in (patch.object(a, "RESOURCES", res), patch.object(gpu_link_pins, "NOAVX_VULKAN_MACOS_X64", self.pin),
                  patch.dict(os.environ, {}, clear=False)):
            p.start()
            self.addCleanup(p.stop)
        os.environ.pop("OPOS_LLAMA_SERVER", None)

    def test_ensure_llama_server_prefers_the_bundle_over_an_official_x64_download(self):
        official = self.rt / "llama-b12682-macos-x64" / "llama-server"
        official.parent.mkdir(parents=True)
        official.write_text("official")
        got = a.ensure_llama_server(self.rt, GPU, "Darwin", "x86_64", allow_download=False)
        self.assertEqual(got, self.rt / DIR / "bin" / "llama-server")

    def test_env_override_still_wins(self):
        mine = self.tmp / "mine-llama-server"
        mine.write_text("x")
        with patch.dict(os.environ, {"OPOS_LLAMA_SERVER": str(mine)}):
            self.assertEqual(a.ensure_llama_server(self.rt, GPU, "Darwin", "x86_64", allow_download=False), mine)

    def test_other_computers_are_unchanged(self):
        with patch.object(a, "find_llama_server", return_value=Path("/x/llama-server")):
            self.assertEqual(a.ensure_llama_server(self.rt, dict(GPU, profile=None), "Darwin", "x86_64"),
                             Path("/x/llama-server"))
            self.assertEqual(a.ensure_llama_server(self.rt, GPU, "Darwin", "arm64"), Path("/x/llama-server"))
        self.assertFalse((self.rt / DIR).exists())

    def test_without_the_artifact_it_falls_back_to_the_old_search(self):
        with patch.object(a, "bundled_noavx_archive", return_value=None), \
                patch.object(a, "find_llama_server", return_value=Path("/x/llama-server")):
            self.assertEqual(a.ensure_llama_server(self.rt, GPU, "Darwin", "x86_64"), Path("/x/llama-server"))

    def test_a_corrupt_bundle_stops_instead_of_running_it(self):
        (self.tmp / "res" / "bundled" / self.pin["name"]).write_bytes(b"corrupt")
        with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
            a.ensure_llama_server(self.rt, GPU, "Darwin", "x86_64", allow_download=False)

    def test_moltenvk_of_the_bundle_beats_the_sdk_and_the_callers_own_setup_wins(self):
        binary = a.ensure_llama_server(self.rt, GPU, "Darwin", "x86_64", allow_download=False)
        home = self.tmp / "home"
        sdk = home / "VulkanSDK" / "macOS" / "share" / "vulkan" / "icd.d"
        sdk.mkdir(parents=True)
        (sdk / "MoltenVK_icd.json").write_text("{}")
        env = a.moltenvk_env({"PATH": "/bin"}, "Darwin", str(home), binary=binary)
        icd = self.rt / DIR / "share" / "vulkan" / "icd.d" / "MoltenVK_icd.json"
        self.assertEqual(env["VK_ICD_FILENAMES"], str(icd))
        self.assertEqual(env["VK_DRIVER_FILES"], str(icd))
        self.assertEqual(env["DYLD_LIBRARY_PATH"], str(self.rt / DIR / "lib"))
        mine = {"VK_DRIVER_FILES": "/mine"}
        self.assertIs(a.moltenvk_env(mine, "Darwin", str(home), binary=binary), mine)

    def test_the_runtime_env_lets_the_server_find_its_libraries(self):
        binary = a.ensure_llama_server(self.rt, GPU, "Darwin", "x86_64", allow_download=False)
        env = a.runtime_env(binary, "Darwin", {"PATH": "/bin"})
        dirs = env["DYLD_LIBRARY_PATH"].split(os.pathsep)
        self.assertIn(str(binary.parent), dirs)
        self.assertIn(str(self.rt / DIR / "lib"), dirs)

    def test_plan_reports_the_bundled_runtime_and_nothing_to_download(self):
        args = SimpleNamespace(budget_mb=None, own_server=True, strict_ports=False, model_path=None, no_extras=False,
                               extras=2, data_dir=self.tmp / "data", runtime_dir=self.rt)
        gpu = {"vendor": "AMD", "name": "AMD Radeon RX 580", "total_mb": 8192, "free_mb": None, "driver": "",
               "backend": "metal", "budget_mb": 6692}
        with patch.object(a, "detect_gpu", return_value=gpu), patch.object(a, "scan_local_ggufs", return_value=[]), \
                patch.object(a, "model_dirs", return_value=[]), \
                patch.object(a.platform, "system", return_value="Darwin"), \
                patch.object(a.platform, "machine", return_value="x86_64"):
            info = a.plan(args)
        self.assertEqual(info["runtime"]["source"], "bundled")
        self.assertFalse(info["runtime"]["download"])
        self.assertEqual(info["runtime"]["asset"], self.pin["name"])

    def test_selftest_reports_the_bundled_artifact(self):
        with patch.object(a, "detect_gpu", return_value={"vendor": "AMD", "name": "x", "backend": "cpu", "budget_mb": 1}), \
                patch("builtins.print") as shown:
            a.selftest()
        facts = json.loads(shown.call_args[0][0])
        self.assertEqual(facts["bundled_noavx_vulkan"], {"name": self.pin["name"], "present": True, "sha256_ok": True})


class PackerIsDeterministicAndPinsRoundTrip(unittest.TestCase):
    def test_same_tree_gives_the_same_bytes(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            make_tree(Path(one))
            os.utime(Path(one) / "bin" / "llama-server", (1, 1))
            make_tree(Path(two))
            self.assertEqual(pack.tar_bytes(Path(one), DIR), pack.tar_bytes(Path(two), DIR))

    def test_write_pin_makes_an_importable_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(__file__).resolve().parent / "gpu_link_pins.py"
            copy = Path(tmp) / "gpu_link_pins.py"
            copy.write_text(src.read_text())
            pin = {"name": "n.tar.gz", "sha256": "a" * 64, "size": 5, "dir": "d", "files": {"bin/llama-server": "b" * 64}}
            pack.write_pin(copy, pin)
            pack.write_pin(copy, pin)  # idempotent
            ns = {}
            exec(compile(copy.read_text(), "pins", "exec"), ns)
            self.assertEqual(ns["NOAVX_VULKAN_MACOS_X64"], dict(pin, url=None))
            self.assertEqual(ns["LLAMA_TAG"], gpu_link_pins.LLAMA_TAG)


class ThePinInTheRepo(unittest.TestCase):
    def test_shape_when_filled_in(self):
        pin = gpu_link_pins.NOAVX_VULKAN_MACOS_X64
        self.assertIsNotNone(pin, "run pack_noavx_vulkan.py --pins on the Intel Mac")
        self.assertRegex(pin["sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("bin/llama-server", pin["files"])
        self.assertIn("lib/libMoltenVK.dylib", pin["files"])
        self.assertIn("lib/libvulkan.1.dylib", pin["files"])
        self.assertIn("share/vulkan/icd.d/MoltenVK_icd.json", pin["files"])
        for rel, digest in pin["files"].items():
            self.assertRegex(digest, r"^[0-9a-f]{64}$")
            self.assertFalse(rel.startswith(("/", "..")))
        self.assertTrue(pin["name"].endswith(".tar.gz") and pin["dir"] in pin["name"])


if __name__ == "__main__":
    unittest.main()

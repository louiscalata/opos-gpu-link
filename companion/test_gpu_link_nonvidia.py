# SPDX-License-Identifier: Apache-2.0
"""Offline coverage for GPU detection and fallback on non-NVIDIA computers."""
import contextlib
import io
import json
import os
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import gpu_link_autosetup as a
from test_gpu_link_autosetup import runner_for, which_only

RX = "Advanced Micro Devices, Inc. [AMD/ATI] Navi 32 [Radeon RX 7800 XT]"
APU = "Advanced Micro Devices, Inc. [AMD/ATI] Granite Ridge [Radeon Graphics]"
UHD = "Intel Corporation CoffeeLake-S GT2 [UHD Graphics 630]"
ARC = "Intel Corporation DG2 [Arc A770]"
NVIDIA = "NVIDIA Corporation GA107M [GeForce RTX 3050 Mobile]"
LLVMPIPE = "Vulkan0: llvmpipe (LLVM 20.1) (8000 MiB, 8000 MiB free)"
RADV = "Vulkan1: AMD Radeon Graphics (RADV GNR) (30000 MiB, 29000 MiB free)"
ANV = "Vulkan2: Intel UHD Graphics 630 (ANV) (8000 MiB, 7000 MiB free)"
MIB = 1024 ** 2


def pci(name, slot="03:00.0", kind="VGA compatible controller"):
    return f"{slot} {kind}: {name} (rev c1)\n"


def vulkan(name, vendor, kind, index=0):
    return (f"GPU{index}:\n\tvendorID = {vendor}\n"
            f"\tdeviceType = PHYSICAL_DEVICE_TYPE_{kind}\n\tdeviceName = {name}\n")


class Detection(unittest.TestCase):
    def setUp(self):
        fixture = tempfile.TemporaryDirectory()
        self.addCleanup(fixture.cleanup)
        self.root = Path(fixture.name)

    def card(self, number, vendor, slot=None, **memory):
        entry = self.root / f"card{number}"
        entry.mkdir()
        device = entry / "device"
        if slot:
            target = self.root / slot
            target.mkdir()
            device.symlink_to(target, target_is_directory=True)
        else:
            device.mkdir()
        (device / "vendor").write_text(vendor)
        (device / "boot_vga").write_text("1")
        for key, mb in memory.items():
            (device / f"mem_info_{key}").write_text(str(mb * MIB))

    def detect(self, table, *, environ=None, system="Linux"):
        run = runner_for(table)
        gpu = a.detect_gpu(run, system, "x86_64", which_only(*table), environ=environ or {}, drm_root=self.root)
        return gpu, [cmd for cmd, _ in run.calls]

    def test_pci_parser_and_vendor_boundaries(self):
        rows = [(RX, "AMD", True), (APU, "AMD", False), (UHD, "Intel", False),
                (ARC, "Intel", True), (NVIDIA, "NVIDIA", True)]
        text = "".join(pci(name, kind=kind) for (name, _, _), kind in zip(
            rows, ("VGA compatible controller", "Display controller", "VGA compatible controller",
                   "Display controller", "3D controller")))
        text += pci("VMware SVGA II Adapter") + pci("Intel Corporation I225", kind="Ethernet controller")
        self.assertEqual(a.parse_lspci(text), [
            {"name": name, "vendor": vendor, "discrete": discrete} for name, vendor, discrete in rows])

    def test_rocm_vram(self):
        rocm = json.dumps({"card0": {"VRAM Total Memory (B)": str(16384 * MIB),
                                    "VRAM Total Used Memory (B)": str(4096 * MIB)}})
        self.assertEqual(a.parse_rocm_smi(rocm), [{"total_mb": 16384, "used_mb": 4096}])
        self.assertEqual(a.parse_rocm_smi("rocm-smi failed"), [])
        gpu, calls = self.detect({"lspci": pci(RX), "rocm-smi": rocm})
        self.assertEqual((gpu["vendor"], gpu["backend"], gpu["integrated"]), ("AMD", "vulkan", False))
        self.assertEqual((gpu["total_mb"], gpu["free_mb"]), (16384, 12288))
        self.assertEqual(gpu["budget_mb"], 12288 - a.VRAM_MARGIN_MB)
        self.assertEqual((gpu["vram_source"], gpu["rocm"]), ("rocm-smi", True))
        self.assertIn(["/usr/bin/rocm-smi", "--showmeminfo", "vram", "--json"], calls)
        self.assertEqual(a.llama_asset("Linux", "x86_64", gpu)[0], "ubuntu-vulkan-x64.tar.gz")

    @unittest.skipIf(sys.platform == "win32", "sysfs fixtures need ':' in directory names")
    def test_sysfs_vram_and_multiple_amd_cards(self):
        self.card(1, "0x1002", "0000:04:00.0", vram_total=16384, vram_used=1536)
        self.card(2, "0x1002", "0000:03:00.0", vram_total=8192, vram_used=100)
        self.card("1-HDMI-A-1", "0x1002", vram_total=32768)
        gpu, _ = self.detect({"lspci": pci(RX) + pci(RX, "04:00.0")})
        self.assertEqual(len(a.read_drm_cards(self.root)), 2)
        self.assertEqual((gpu["drm_card"], gpu["total_mb"], gpu["vram_source"]), ("card1", 16384, "sysfs"))
        self.assertEqual(gpu["budget_mb"], 16384 - 1536 - a.VRAM_MARGIN_MB)
        self.assertEqual(a.gpu_memory_used_mb(gpu, drm_root=self.root), 1536)

    def test_amd_apu_shared_memory(self):
        self.card(0, "0x1002", vram_total=2048, vram_used=500, gtt_total=30720, gtt_used=150)
        with patch.object(Path, "read_text", autospec=True, side_effect=self.with_available_memory(32768)):
            gpu, _ = self.detect({"lspci": pci(APU)})
        self.assertTrue(gpu["integrated"])
        self.assertEqual((gpu["total_mb"], gpu["budget_mb"], gpu["vram_source"]), (2048, 3500, "sysfs"))
        self.assertEqual(a.gpu_memory_used_mb(gpu, drm_root=self.root), 650)

    def with_available_memory(self, available):
        read_text = Path.read_text

        def read(path, *args, **kwargs):
            if path == Path("/proc/meminfo"):
                return f"MemAvailable: {available * 1024} kB\n"
            return read_text(path, *args, **kwargs)
        return read

    def test_integrated_budget_caps_on_available_ram_and_gtt(self):
        for available, gtt, expected in [(1000, 4096, 500), (16000, 2048, 1024), (16000, 0, 0)]:
            with self.subTest(available=available, gtt=gtt), patch.object(
                    Path, "read_text", autospec=True, side_effect=self.with_available_memory(available)):
                self.assertEqual(a.integrated_budget(gtt), expected)

    @unittest.skipIf(sys.platform == "win32", "sysfs fixtures need ':' in directory names")
    def test_intel_integrated_and_discrete(self):
        self.card(0, "0x8086", "0000:00:02.0")
        self.card(1, "0x8086", "0000:03:00.0", vram_total=16384)
        with patch.object(a, "integrated_budget", return_value=3500):
            gpu, _ = self.detect({"lspci": pci(UHD, "00:02.0")})
        self.assertEqual((gpu["vendor"], gpu["backend"], gpu["integrated"]), ("Intel", "vulkan", True))
        gpu, _ = self.detect({"lspci": pci(UHD, "00:02.0") + pci(ARC)})
        self.assertEqual((gpu["name"], gpu["integrated"], gpu["vram_source"]), (ARC, False, "sysfs"))
        self.assertEqual(gpu["budget_mb"], 16384 - a.VRAM_MARGIN_MB)

    def test_nouveau_hybrid_and_hidden_nvidia_smi_not_called(self):
        text = pci(UHD, "00:02.0") + pci(NVIDIA, kind="3D controller")
        gpu, _ = self.detect({"lspci": text})
        self.assertEqual((gpu["vendor"], gpu["backend"], gpu["budget_mb"]), ("NVIDIA", "vulkan", 3500))
        gpu, calls = self.detect(
            {"lspci": text, "nvidia-smi": "RTX 3050, 8192, 8000, 595.99.02"},
            environ={"OPOS_GPU_LINK_HIDE_NVIDIA": "1"})
        self.assertEqual(gpu["vendor"], "Intel")
        self.assertTrue(gpu["nvidia_hidden"])
        self.assertNotIn("/usr/bin/nvidia-smi", [cmd[0] for cmd in calls])

    def test_vulkan_probe_fallback_and_classification(self):
        summary = vulkan("llvmpipe", "0x10005", "CPU") + vulkan("Intel Arc Graphics", "0x8086", "INTEGRATED_GPU", 1)
        self.assertEqual(a.parse_vulkaninfo_summary(summary)[0],
                         {"name": "llvmpipe", "type": "CPU", "vendor_id": 0x10005})
        for system in ("Linux", "Windows"):
            with self.subTest(system=system):
                gpu, _ = self.detect({"vulkaninfo": summary}, system=system)
                self.assertEqual((gpu["vendor"], gpu["name"], gpu["integrated"]),
                                 ("Intel", "Intel Arc Graphics", True))
        gpu, _ = self.detect({"lspci": pci("Intel Corporation Arc Graphics"), "vulkaninfo": summary})
        self.assertTrue(gpu["integrated"])
        self.assertEqual(gpu["name"], "Intel Corporation Arc Graphics")

    def test_missing_probes_and_software_only_are_cpu(self):
        for table in ({}, {"vulkaninfo": vulkan("llvmpipe", "0x10005", "CPU")}):
            with self.subTest(table=table):
                gpu, _ = self.detect(table)
                self.assertEqual((gpu["name"], gpu["backend"], gpu["budget_mb"]), ("CPU only", "cpu", 2000))
                self.assertEqual(a.llama_asset("Linux", "x86_64", gpu)[0], "ubuntu-x64.tar.gz")

    def test_missing_optional_tools_fail_soft(self):
        def missing(cmd, **kwargs):
            raise FileNotFoundError(cmd[0])

        gpu = a.detect_gpu(missing, "Linux", "x86_64", which_only("lspci", "vulkaninfo", "nvidia-smi"),
                           environ={}, drm_root=self.root)
        self.assertEqual(gpu["backend"], "cpu")

    def test_windows_vendor_boundaries(self):
        for name, vendor in ((UHD, "Intel"), (NVIDIA, "NVIDIA"), ("Arc A770", "Intel"),
                             ("ATI Radeon RX 7800 XT", "AMD"), ("Arcade Corporation", "none")):
            with self.subTest(name=name):
                gpu, _ = self.detect({"powershell": name}, system="Windows")
                self.assertEqual(gpu["vendor"], vendor)


class Visibility(unittest.TestCase):
    def test_environment_switches(self):
        for value in ("1", " True ", "YES", "On", "false", "0", ""):
            with self.subTest(flag=value):
                self.assertEqual(a.hide_nvidia({"OPOS_GPU_LINK_HIDE_NVIDIA": value}),
                                 value.strip().lower() in {"1", "true", "yes", "on"})
        for value in ("", " -1 ", "NoDevFiles", "0", "0,1"):
            with self.subTest(cuda=value):
                self.assertEqual(a.hide_nvidia({"CUDA_VISIBLE_DEVICES": value}), value not in ("0", "0,1"))
        self.assertFalse(a.hide_nvidia({}))

    def test_classifies_real_gpu_devices(self):
        nvidia = "Vulkan3: NVIDIA GeForce RTX 5080"
        cuda = "CUDA0: generic device"
        lines = [LLVMPIPE, RADV, ANV, nvidia, cuda, "Vulkan4: lavapipe", "Vulkan5: Software Renderer",
                 "Vulkan6: swrast", "Vulkan7: CPU"]
        self.assertEqual(a.classify_devices(lines), [RADV, ANV, nvidia, cuda])
        self.assertEqual(a.classify_devices(lines, hide=True), [RADV, ANV])

    def test_real_5080_box_list_devices_keeps_ryzen_igpu_when_nvidia_hidden(self):
        # Verbatim `llama-server --list-devices` from the RTX 5080 Ubuntu box (b12682 Vulkan build, 25 Nov 2026).
        lines = ["Vulkan0: NVIDIA GeForce RTX 5080 (16303 MiB, 9602 MiB free)",
                 "Vulkan1: AMD Ryzen 9 9950X 16-Core Processor (RADV RAPHAEL_MENDOCINO) (32072 MiB, 32042 MiB free)"]
        self.assertEqual(a.classify_devices(lines, hide=True), lines[1:])
        self.assertEqual(a.classify_devices(lines), lines)

    def test_linux_icd_allowlist(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, library in {"nvidia": "libGLX.so", "foo": "libGLX_nvidia.so.0", "radeon": "radeon.so",
                                  "intel": "intel.so", "lvp": "lvp.so", "nouveau": "libvulkan_nouveau.so"}.items():
                (root / ("foo.json" if name == "foo" else f"{name}_icd.json")).write_text(json.dumps({"ICD": {"library_path": library}}))
            (root / "invalid.json").write_text("{")
            source = {"CUDA_VISIBLE_DEVICES": "0", "VK_DRIVER_FILES": "previous"}
            result = a.hide_nvidia_env(source, system="Linux", icd_dirs=[root])
            self.assertEqual(result["CUDA_VISIBLE_DEVICES"], "")
            self.assertEqual(source["CUDA_VISIBLE_DEVICES"], "0")
            self.assertNotIn("GGML_VK_VISIBLE_DEVICES", result)
            self.assertEqual(result["VK_ICD_FILENAMES"], result["VK_DRIVER_FILES"])
            self.assertEqual({Path(path).name for path in result["VK_DRIVER_FILES"].split(os.pathsep)},
                             {"radeon_icd.json", "intel_icd.json", "lvp_icd.json"})
            result = a.hide_nvidia_env({"GGML_VK_VISIBLE_DEVICES": "7"}, system="Linux", icd_dirs=[])
            self.assertIn("GGML_VK_VISIBLE_DEVICES", result)
            self.assertEqual(result["VK_DRIVER_FILES"], result["VK_ICD_FILENAMES"])
            self.assertTrue(result["VK_DRIVER_FILES"].startswith("/nonexistent/"))
            for system in ("Windows", "Darwin"):
                self.assertEqual(a.hide_nvidia_env(source, system=system, icd_dirs=[root]),
                                 dict(source, CUDA_VISIBLE_DEVICES=""))

    def test_flag_and_selftest(self):
        self.assertTrue(a.arguments(["--hide-nvidia"]).hide_nvidia)
        output = io.StringIO()
        with patch.object(a, "os", wraps=os) as fake_os, patch.object(a, "find_llama_server", return_value=None), \
                patch.object(a, "detect_gpu", return_value={"backend": "cpu"}), \
                patch.object(a, "RESOURCES", Path("/nonexistent")), patch.object(a, "cpu_has_avx", return_value=True), \
                patch.object(a.platform, "platform", return_value="test-platform"), \
                contextlib.redirect_stdout(output):
            fake_os.environ = {}
            self.assertEqual(a.main(["--hide-nvidia", "--selftest"]), 0)
            self.assertEqual(fake_os.environ["OPOS_GPU_LINK_HIDE_NVIDIA"], "1")
        self.assertTrue(json.loads(output.getvalue())["gpu_hidden_nvidia"])


class Fallback(unittest.TestCase):
    def test_catalog_right_sizes_models(self):
        large = a.pick_model(16384 - a.VRAM_MARGIN_MB, [])[1]
        for budget in (a.CPU_BUDGET_MB, a.IGPU_BUDGET_CAP_MB):
            model = a.pick_model(budget, [])[1]
            self.assertLess(model["size_mb"], large["size_mb"])
            self.assertLessEqual(a.need_mb(model["size_mb"]), budget)

    def test_vulkan_buffers_are_proof_only_with_usable_devices(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / "server.log"
            log.write_text("Vulkan0 model buffer size = 1234 MiB")
            server = Mock(log_path=log)
            self.assertTrue(a.verify_gpu(server, {"vendor": "AMD"}, devices=[RADV])[0])
            self.assertFalse(a.verify_gpu(server, {"vendor": "AMD"}, devices=a.classify_devices([LLVMPIPE]))[0])

    def test_software_only_runtime_replans_and_stops(self):
        for override, prefer in ((None, None), (5000, "local-model")):
            with self.subTest(override=override), contextlib.ExitStack() as stack:
                args = a.arguments(["--own-server", "--no-download"])
                args.budget_mb, args.model_path = override, prefer
                gpu = {"vendor": "AMD", "name": RX, "backend": "vulkan", "budget_mb": 15000, "nvidia_hidden": True}
                info = {"gpu": gpu, "runtime": {"type": "llama-server"},
                        "model": {"size_mb": 9000}, "extras": [{"size_mb": 1000}]}
                binary = Path("/unused/llama-server")
                server = Mock(base_url="http://fake", log_path=Path("/unused/server.log"))
                local = [{"path": "/unused/local-model.gguf", "name": "local-model.gguf", "size_mb": 2300}]
                fake_env = stack.enter_context(patch.object(a, "os", wraps=os))
                fake_env.environ = {}
                mocks = {}
                for name, value in {
                    "ensure_llama_server": binary, "runtime_env": {}, "probe_binary": (True, "fake"),
                    "list_devices": [LLVMPIPE, "CUDA0: NVIDIA"], "ensure_model": (Path("/unused/model"), "Test model"),
                    "launch_llama_server": server, "wait_healthy": True, "verify_gpu": (False, []),
                    "choose_port": 18090, "new_key": None, "write_key_file": None, "model_dirs": [],
                    "scan_local_ggufs": local,
                }.items():
                    mocks[name] = stack.enter_context(patch.object(a, name, return_value=value))
                output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                runtime = a.start_runtime(args, info, runner=runner_for({}))
                runtime.stop()
                server.stop.assert_called_once_with()
                self.assertEqual(runtime.servers, [])
                self.assertEqual(len(runtime.lanes), 1)
                self.assertEqual((info["gpu"]["backend"], info["extras"]), ("cpu", []))
                budget = override if override is not None else a.CPU_BUDGET_MB
                self.assertEqual(info["gpu"]["budget_mb"], budget)
                self.assertLessEqual(info["model"]["need_mb"], budget)
                self.assertLess(info["model"]["size_mb"], 9000)
                self.assertEqual(info["model"]["choice"], "local" if prefer else "download")
                self.assertIn("No usable GPU backend found for", output.getvalue())
                self.assertIn("Running on the CPU with a smaller model (answers will be slower)", output.getvalue())
                self.assertEqual(mocks["launch_llama_server"].call_args.args[5], "cpu")
                self.assertEqual(mocks["list_devices"].call_args.args[1]["CUDA_VISIBLE_DEVICES"], "")
                mocks["model_dirs"].assert_called_once_with(here=args.data_dir)

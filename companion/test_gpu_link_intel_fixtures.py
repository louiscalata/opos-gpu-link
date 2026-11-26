# SPDX-License-Identifier: Apache-2.0
"""Fixture tests for hardware the project does not own: Intel GPUs on Windows and Intel Macs that are not the
Mac Pro RX 580. Fixtures follow the real output shapes (Win32_VideoController names, DirectX memory rows,
system_profiler). They check selection, budgets and fallbacks only; no real Intel GPU was run."""
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_link_autosetup as a  # noqa: E402

SMI_RTX = "NVIDIA GeForce RTX 3050 Laptop GPU, 4096, 3500, 566.36\n"


def win_runner(names, memory=None, smi=None):
    def run(cmd, **kwargs):
        name = Path(cmd[0]).name.lower()
        out = None
        if name.startswith("nvidia-smi"):
            out = smi
        elif name.startswith("powershell"):
            out = (json.dumps(memory) if memory is not None else "[]") if "GPU Adapter Memory" in cmd[-1] else names
        return SimpleNamespace(returncode=0 if out is not None else 1, stdout=(out or "").encode())
    return run


def which(*have):
    return lambda n: n if n in have else None


class IntelOnWindows(unittest.TestCase):
    def detect(self, names, memory=None, smi=None, only=None, environ=None):
        run = win_runner(names, memory, smi)
        return a.detect_gpu(run, "Windows", "AMD64", which("nvidia-smi") if smi else which(), only=only,
                            environ=environ or {})

    def test_uhd_630_igpu_is_vulkan_with_the_fixed_small_budget(self):
        gpu = self.detect("Intel(R) UHD Graphics 630\n", [{"name": "Intel(R) UHD Graphics 630", "total_mb": 128, "used_mb": 40}])
        self.assertEqual((gpu["vendor"], gpu["backend"], gpu["budget_mb"]), ("Intel", "vulkan", 3500))
        self.assertIsNone(gpu["total_mb"])  # 128 MB carve-out is below the measurement floor: not trusted

    def test_arc_a770_uses_measured_free_vram_minus_margin(self):
        gpu = self.detect("Intel(R) Arc(TM) A770 Graphics\n",
                          [{"name": "Intel(R) Arc(TM) A770 Graphics", "total_mb": 16304, "used_mb": 900}])
        self.assertEqual((gpu["vendor"], gpu["backend"]), ("Intel", "vulkan"))
        self.assertEqual(gpu["budget_mb"], 16304 - 900 - a.VRAM_MARGIN_MB)
        self.assertEqual(gpu["memory_source"], "windows-gpu-counters")

    def test_arc_a380_6gb(self):
        gpu = self.detect("Intel(R) Arc(TM) A380 Graphics\n",
                          [{"name": "Intel(R) Arc(TM) A380 Graphics", "total_mb": 6144, "used_mb": 300}])
        self.assertEqual(gpu["budget_mb"], 6144 - 300 - a.VRAM_MARGIN_MB)

    def test_hybrid_laptop_prefers_nvidia(self):
        names = "Intel(R) UHD Graphics\nNVIDIA GeForce RTX 3050 Laptop GPU\n"
        gpu = self.detect(names, smi=SMI_RTX)
        self.assertEqual((gpu["vendor"], gpu["backend"]), ("NVIDIA", "cuda"))

    def test_hybrid_laptop_gpu_intel_picks_the_igpu_and_hides_nvidia(self):
        names = "Intel(R) UHD Graphics\nNVIDIA GeForce RTX 3050 Laptop GPU\n"
        gpu = self.detect(names, smi=SMI_RTX, only="intel")
        self.assertEqual((gpu["vendor"], gpu["backend"], gpu["forced"]), ("Intel", "vulkan", "intel"))

    def test_hybrid_laptop_hide_nvidia_falls_back_to_the_igpu(self):
        names = "Intel(R) UHD Graphics\nNVIDIA GeForce RTX 3050 Laptop GPU\n"
        gpu = self.detect(names, smi=SMI_RTX, environ={"OPOS_GPU_LINK_HIDE_NVIDIA": "1"})
        self.assertEqual((gpu["vendor"], gpu["backend"]), ("Intel", "vulkan"))
        self.assertTrue(gpu["nvidia_hidden"])

    def test_gpu_amd_on_an_intel_only_pc_is_cpu_never_the_intel_gpu(self):
        gpu = self.detect("Intel(R) UHD Graphics 630\n", only="amd")
        self.assertEqual((gpu["backend"], gpu["vendor"]), ("cpu", "none"))

    def test_virtual_and_basic_adapters_are_not_a_gpu(self):
        for names in ("Microsoft Basic Display Adapter\n", "Microsoft Hyper-V Video\n", "Microsoft Remote Display Adapter\n", ""):
            gpu = self.detect(names)
            self.assertEqual((gpu["backend"], gpu["budget_mb"]), ("cpu", a.CPU_BUDGET_MB), names)

    def test_two_identical_intel_adapters_get_no_guessed_measurement(self):
        rows = [{"name": "Intel(R) Arc(TM) A770 Graphics", "total_mb": 16304, "used_mb": 100},
                {"name": "Intel(R) Arc(TM) A770 Graphics", "total_mb": 16304, "used_mb": 15000}]
        gpu = self.detect("Intel(R) Arc(TM) A770 Graphics\nIntel(R) Arc(TM) A770 Graphics\n", rows)
        self.assertEqual(gpu["budget_mb"], 3500)  # unmeasured: the fixed small budget, not a coin flip

    def test_intel_gpu_picks_the_vulkan_device_next_to_nvidia(self):
        intel = {"backend": "vulkan", "vendor": "Intel", "name": "Intel(R) UHD Graphics"}
        devices = ["Vulkan0: NVIDIA GeForce RTX 3050 Laptop GPU (4096 MiB, 3500 MiB free)",
                   "Vulkan1: Intel(R) UHD Graphics (8000 MiB, 7000 MiB free)"]
        self.assertEqual(a.pick_vulkan_device(devices, intel), "Vulkan1")


def mac_runner(profiler, memsize="17179869184", brand="Intel(R) Core(TM) i7-9750H CPU @ 2.60GHz"):
    def run(cmd, **kwargs):
        key = (Path(cmd[0]).name, cmd[1] if len(cmd) > 1 else "")
        if key == ("sysctl", "hw.memsize") or cmd[-1] == "hw.memsize":
            out = memsize
        elif cmd[-1] == "machdep.cpu.brand_string":
            out = brand
        elif Path(cmd[0]).name == "system_profiler":
            out = profiler
        else:
            out = None
        return SimpleNamespace(returncode=0 if out is not None else 1, stdout=(out or "").encode())
    return run


IRIS = "Graphics/Displays:\n\n    Intel UHD Graphics 630:\n\n      Chipset Model: Intel UHD Graphics 630\n      VRAM (Dynamic, Max): 1536 MB\n"
GTX680 = "Graphics/Displays:\n\n    NVIDIA GeForce GTX 680:\n\n      Chipset Model: NVIDIA GeForce GTX 680\n      VRAM (Total): 2 GB\n"
HD7950 = "Graphics/Displays:\n\n    AMD Radeon HD 7950:\n\n      Chipset Model: AMD Radeon HD 7950\n      VRAM (Total): 3 GB\n"
VEGA = "Graphics/Displays:\n\n    AMD Radeon Pro Vega 20:\n\n      Chipset Model: AMD Radeon Pro Vega 20\n      VRAM (Total): 4 GB\n"
NO_GPU = "Graphics/Displays:\n"


def plan_for(gpu, avx, environ=None, budget_mb=None):
    args = SimpleNamespace(budget_mb=budget_mb, own_server=True, strict_ports=False, model_path=None, no_extras=False,
                           extras=2, data_dir=Path("/nonexistent-data"), runtime_dir=Path("/nonexistent-rt"), gpu=None)
    with patch.object(a, "detect_gpu", return_value=dict(gpu)), patch.object(a, "scan_local_ggufs", return_value=[]), \
            patch.object(a, "find_llama_server", return_value=None), patch.object(a, "model_dirs", return_value=[]), \
            patch.object(a.platform, "system", return_value="Darwin"), \
            patch.object(a.platform, "machine", return_value="x86_64"), \
            patch.object(a, "cpu_has_avx", return_value=avx), patch.dict(a.os.environ, environ or {}, clear=False):
        return a.plan(args)


class IntelMacWithoutTheRx580Profile(unittest.TestCase):
    def detect(self, profiler):
        return a.detect_gpu(mac_runner(profiler), "Darwin", "x86_64", which())

    def test_intel_igpu_mac_answers_on_the_cpu(self):
        gpu = self.detect(IRIS)
        self.assertEqual((gpu["vendor"], gpu["backend"], gpu["budget_mb"]), ("Intel Mac GPU", "cpu", a.CPU_BUDGET_MB))
        self.assertIn("using the CPU", gpu["note"])

    def test_old_nvidia_mac_answers_on_the_cpu(self):
        self.assertEqual(self.detect(GTX680)["backend"], "cpu")

    def test_amd_cards_on_a_mac_keep_the_metal_path(self):
        self.assertEqual((self.detect(HD7950)["backend"], self.detect(VEGA)["backend"]), ("metal", "metal"))
        self.assertEqual(self.detect(VEGA)["budget_mb"], 4096 - 1500)

    def test_no_gpu_listed_is_the_cpu(self):
        gpu = self.detect(NO_GPU)
        self.assertEqual((gpu["vendor"], gpu["backend"]), ("Intel Mac", "cpu"))

    def test_intel_igpu_mac_with_avx_gets_a_small_cpu_model_and_the_official_runtime(self):
        info = plan_for(self.detect(IRIS), avx=True)
        self.assertEqual(info["gpu"]["backend"], "cpu")
        self.assertEqual(info["extras"], [])
        self.assertEqual(info["runtime"]["asset"], "macos-x64.tar.gz")
        self.assertLessEqual(info["model"]["need_mb"], a.CPU_BUDGET_MB)
        self.assertFalse(a.wants_noavx_vulkan(info["gpu"], "Darwin", "x86_64", {}))

    def test_no_avx_mac_with_another_gpu_uses_the_bundled_runtime_on_the_cpu(self):
        for profiler in (HD7950, GTX680, IRIS):
            info = plan_for(self.detect(profiler), avx=False)
            self.assertEqual(info["gpu"]["backend"], "cpu", profiler)
            self.assertTrue(info["gpu"]["noavx_cpu"])
            self.assertEqual(info["extras"], [])
            self.assertLessEqual(info["model"]["need_mb"], a.CPU_BUDGET_MB)
            self.assertTrue(a.wants_noavx_vulkan(info["gpu"], "Darwin", "x86_64", {}))
            self.assertNotEqual(info["runtime"]["asset"], "macos-x64.tar.gz")  # not the build that cannot start there

    def test_no_avx_mac_without_any_gpu_listed_also_gets_the_bundled_runtime(self):
        info = plan_for(self.detect(NO_GPU), avx=False)
        self.assertTrue(info["gpu"]["noavx_cpu"])
        self.assertTrue(a.wants_noavx_vulkan(info["gpu"], "Darwin", "x86_64", {}))

    def test_no_avx_mac_explains_why_it_is_on_the_cpu(self):
        info = plan_for(self.detect(HD7950), avx=False)
        self.assertIn("no AVX", info["gpu"]["note"])
        self.assertIn("Radeon HD 7950", info["gpu"]["note"])

    def test_the_rx580_with_the_profile_off_is_the_same_clean_cpu_fallback(self):
        rx580 = {"vendor": "AMD", "name": "AMD Radeon RX 580", "total_mb": 8192, "free_mb": None, "driver": "",
                 "backend": "metal", "budget_mb": 6692}
        info = plan_for(rx580, avx=False, environ={"OPOS_GPU_LINK_PROFILE": "none"})
        self.assertNotIn("profile", info["gpu"])
        self.assertEqual((info["gpu"]["backend"], info["gpu"]["noavx_cpu"]), ("cpu", True))

    def test_the_rx580_profile_is_untouched(self):
        rx580 = {"vendor": "AMD", "name": "AMD Radeon RX 580", "total_mb": 8192, "free_mb": None, "driver": "",
                 "backend": "metal", "budget_mb": 6692}
        info = plan_for(rx580, avx=False)
        self.assertEqual((info["gpu"]["profile"], info["gpu"]["backend"]), (a.PROFILE_RX580, "metal"))
        self.assertNotIn("noavx_cpu", info["gpu"])

    def test_an_explicit_llama_server_is_never_replaced(self):
        info = plan_for(self.detect(HD7950), avx=False, environ={"OPOS_LLAMA_SERVER": "/mine/llama-server"})
        self.assertEqual(info["gpu"]["backend"], "metal")
        self.assertNotIn("noavx_cpu", info["gpu"])

    def test_budget_override_still_wins(self):
        info = plan_for(self.detect(HD7950), avx=False, budget_mb=3000)
        self.assertEqual(info["gpu"]["budget_mb"], 3000)

    def test_other_systems_are_not_affected(self):
        gpu = {"vendor": "AMD", "name": "AMD Radeon HD 7950", "backend": "vulkan", "budget_mb": 3500}
        self.assertFalse(a.no_avx_mac_without_profile(gpu, "Linux", "x86_64", {}, avx=False))
        self.assertFalse(a.no_avx_mac_without_profile(gpu, "Darwin", "arm64", {}, avx=False))
        self.assertFalse(a.no_avx_mac_without_profile(gpu, "Darwin", "x86_64", {}, avx=True))
        self.assertTrue(a.no_avx_mac_without_profile(gpu, "Darwin", "x86_64", {}, avx=False))


if __name__ == "__main__":
    unittest.main()

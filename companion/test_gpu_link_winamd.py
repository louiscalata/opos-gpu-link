# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the AMD-only (Vulkan) path, the GPU-vendor switch and the old-NVIDIA-driver (CUDA 12.4) branch.
No network, no GPU, no adb."""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_link_autosetup as a  # noqa: E402

SMI_3080TI = "NVIDIA GeForce RTX 3080 Ti, 12288, 4229, 610.60\n"
NAMES = "NVIDIA GeForce RTX 3080 Ti\nMicrosoft Basic Render Driver\nAMD Radeon RX 5700 XT\n"
MEMORY_JSON = json.dumps([
    {"name": "NVIDIA GeForce RTX 3080 Ti", "total_mb": 12086, "used_mb": 8062},
    {"name": "AMD Radeon RX 5700 XT", "total_mb": 8152, "used_mb": 6303},
])
VULKAN_DEVICES = ["Vulkan0: AMD Radeon RX 5700 XT (8176 MiB, 5833 MiB free)",
                  "Vulkan1: NVIDIA GeForce RTX 3080 Ti (12300 MiB, 11528 MiB free)"]


def windows_runner(memory=MEMORY_JSON, smi=SMI_3080TI, names=NAMES):
    calls = []

    def run(cmd, **kwargs):
        calls.append(list(cmd))
        name = Path(cmd[0]).name.lower()
        if name.startswith("nvidia-smi"):
            out = smi
        elif name.startswith("powershell"):
            out = memory if "GPU Adapter Memory" in cmd[-1] else names
        else:
            out = None
        if out is None:
            return SimpleNamespace(returncode=1, stdout=b"")
        return SimpleNamespace(returncode=0, stdout=out.encode())
    run.calls = calls
    return run


def which_smi(n):
    return "nvidia-smi" if n == "nvidia-smi" else None


class ForceAmd(unittest.TestCase):
    def detect(self, only, **kw):
        run = windows_runner(**kw)
        return a.detect_gpu(run, "Windows", "AMD64", which_smi, only=only, environ={}), run

    def test_auto_still_prefers_nvidia(self):
        gpu, _ = self.detect("auto")
        self.assertEqual((gpu["vendor"], gpu["backend"], gpu["cuda_variant"]), ("NVIDIA", "cuda", "win-cuda-13.5-x64"))

    def test_amd_hides_cuda_and_never_calls_nvidia_smi(self):
        gpu, run = self.detect("amd")
        self.assertEqual((gpu["vendor"], gpu["backend"]), ("AMD", "vulkan"))
        self.assertEqual(gpu["name"], "AMD Radeon RX 5700 XT")
        self.assertEqual(gpu["forced"], "amd")
        self.assertNotIn("cuda_variant", gpu)
        self.assertFalse(any(Path(c[0]).name.lower().startswith("nvidia-smi") for c in run.calls))
        self.assertEqual(a.llama_asset("Windows", "AMD64", gpu)[0], "win-vulkan-x64.zip")

    def test_amd_budget_is_the_measured_free_vram_not_a_fixed_3_5_gb(self):
        gpu, _ = self.detect("amd")
        self.assertEqual((gpu["total_mb"], gpu["free_mb"]), (8152, 8152 - 6303))
        self.assertEqual(gpu["budget_mb"], 8152 - 6303 - a.VRAM_MARGIN_MB)
        self.assertEqual(gpu["memory_source"], "windows-gpu-counters")

    def test_amd_without_a_measurement_keeps_the_fixed_budget(self):
        gpu, _ = self.detect("amd", memory="not json")
        self.assertEqual(gpu["budget_mb"], 3500)
        self.assertIsNone(gpu["free_mb"])

    def test_igpu_with_tiny_dedicated_memory_keeps_the_fixed_budget(self):
        small = json.dumps([{"name": "AMD Radeon(TM) Graphics", "total_mb": 512, "used_mb": 100}])
        gpu, _ = self.detect("amd", memory=small, names="AMD Radeon(TM) Graphics\n")
        self.assertEqual(gpu["budget_mb"], 3500)

    def test_budget_never_negative_when_the_card_is_full(self):
        full = json.dumps([{"name": "AMD Radeon RX 5700 XT", "total_mb": 8152, "used_mb": 8000}])
        gpu, _ = self.detect("amd", memory=full)
        self.assertEqual(gpu["budget_mb"], 0)

    def test_nvidia_choice_ignores_amd_and_missing_nvidia_means_cpu(self):
        gpu, _ = self.detect("nvidia")
        self.assertEqual((gpu["vendor"], gpu["forced"]), ("NVIDIA", "nvidia"))
        run = windows_runner()
        with tempfile.TemporaryDirectory() as empty, patch.dict(os.environ, {"SystemRoot": empty}):
            # no nvidia-smi on PATH or in System32 (a real PC may have it there, so point SystemRoot elsewhere)
            none = a.detect_gpu(run, "Windows", "AMD64", lambda n: None, only="nvidia", environ={})
        # forced means forced: no NVIDIA card -> CPU, never silently another GPU
        self.assertEqual((none["vendor"], none["backend"], none["forced"]), ("none", "cpu", "nvidia"))
        self.assertIn("no NVIDIA", none["name"])

    def test_amd_requested_but_absent_says_so(self):
        gpu = a.detect_gpu(windows_runner(names="NVIDIA GeForce RTX 3080 Ti\n"), "Windows", "AMD64", which_smi,
                           only="amd", environ={})
        self.assertEqual((gpu["backend"], gpu["vendor"], gpu["forced"]), ("cpu", "none", "amd"))
        self.assertIn("no AMD", gpu["name"])

    def test_cpu_choice_uses_no_gpu(self):
        gpu, run = self.detect("cpu")
        self.assertEqual(gpu["backend"], "cpu")
        self.assertEqual(run.calls, [])

    def test_env_variable_selects_the_vendor(self):
        run = windows_runner()
        gpu = a.detect_gpu(run, "Windows", "AMD64", which_smi, environ={a.GPU_ENV: "AMD"})
        self.assertEqual(gpu["vendor"], "AMD")
        self.assertEqual(a.normalize_gpu_choice("garbage"), "auto")
        self.assertEqual(a.normalize_gpu_choice(None), "auto")

    def test_linux_amd_uses_sysfs_memory(self):
        with tempfile.TemporaryDirectory() as d:
            dev = Path(d) / "card0" / "device"
            dev.mkdir(parents=True)
            (dev / "vendor").write_text("0x1002\n")
            (dev / "mem_info_vram_total").write_text(str(8 * 1024 ** 3))
            (dev / "mem_info_vram_used").write_text(str(2 * 1024 ** 3))
            self.assertEqual(a.linux_amd_memory(d), {"total_mb": 8192, "used_mb": 2048, "source": "amdgpu-sysfs"})
            (dev / "vendor").write_text("0x10de\n")
            self.assertIsNone(a.linux_amd_memory(d))

    def test_vram_used_probe_follows_the_chosen_gpu(self):
        run = windows_runner()
        with patch("gpu_link_autosetup.platform.system", return_value="Windows"):
            amd = {"vendor": "AMD", "name": "AMD Radeon RX 5700 XT", "backend": "vulkan"}
            self.assertEqual(a.vram_used_mb(amd, run), 6303)
            self.assertEqual(a.vram_used_mb({"vendor": "NVIDIA", "backend": "cuda"}, windows_runner(smi="8062\n")), 8062)
        self.assertIsNone(a.vram_used_mb({"vendor": "Apple", "backend": "metal"}, run))

    def test_two_identical_cards_cannot_be_told_apart_so_no_measurement(self):
        rows = [{"name": "AMD Radeon RX 5700 XT", "total_mb": 8152, "used_mb": 1},
                {"name": "AMD Radeon RX 5700 XT", "total_mb": 8152, "used_mb": 7000}]
        self.assertIsNone(a.match_adapter(rows, "AMD Radeon RX 5700 XT"))

    def test_linux_prefers_the_card_with_the_most_memory(self):
        with tempfile.TemporaryDirectory() as d:
            for card, total in (("card0", 512 * 1024 ** 2), ("card1", 16 * 1024 ** 3)):
                dev = Path(d) / card / "device"
                dev.mkdir(parents=True)
                (dev / "vendor").write_text("0x1002\n")
                (dev / "mem_info_vram_total").write_text(str(total))
                (dev / "mem_info_vram_used").write_text("1048576")
            self.assertEqual(a.linux_amd_memory(d)["total_mb"], 16384)

    def test_forced_vendor_on_macos_is_cpu_unless_it_matches(self):
        def run(cmd, **kw):
            return SimpleNamespace(returncode=0, stdout=b"17179869184\n")
        apple = a.detect_gpu(run, "Darwin", "arm64", lambda n: None, only="auto", environ={})
        self.assertEqual(apple["backend"], "metal")
        for choice in ("amd", "intel", "nvidia"):
            forced = a.detect_gpu(run, "Darwin", "arm64", lambda n: None, only=choice, environ={})
            self.assertEqual((forced["backend"], forced["forced"]), ("cpu", choice))
        self.assertEqual(a.detect_gpu(run, "Darwin", "arm64", lambda n: None, only="cpu", environ={})["backend"], "cpu")

    def test_adapter_match_ignores_case_and_trademarks(self):
        rows = [{"name": "Intel(R) Arc(TM) A770 Graphics", "total_mb": 16000, "used_mb": 1}]
        self.assertIsNotNone(a.match_adapter(rows, "intel arc a770 graphics"))
        self.assertIsNone(a.match_adapter(rows, "AMD Radeon RX 5700 XT"))


class VulkanDevice(unittest.TestCase):
    def test_picks_the_amd_device_whichever_index_it_has(self):
        amd = {"backend": "vulkan", "vendor": "AMD", "name": "AMD Radeon RX 5700 XT"}
        self.assertEqual(a.pick_vulkan_device(VULKAN_DEVICES, amd), "Vulkan0")
        self.assertEqual(a.pick_vulkan_device(VULKAN_DEVICES[::-1], amd), "Vulkan0")  # order in the list is irrelevant
        reordered = ["Vulkan0: NVIDIA GeForce RTX 3080 Ti (12300 MiB, 1 MiB free)",
                     "Vulkan1: AMD Radeon RX 5700 XT (8176 MiB, 5833 MiB free)"]
        self.assertEqual(a.pick_vulkan_device(reordered, amd), "Vulkan1")

    def test_old_nvidia_driver_vulkan_fallback_picks_the_nvidia_device(self):
        nv = {"backend": "vulkan", "vendor": "NVIDIA", "name": "NVIDIA GeForce RTX 3080 Ti"}
        self.assertEqual(a.pick_vulkan_device(VULKAN_DEVICES, nv), "Vulkan1")

    def test_vendor_words_match_when_names_differ(self):
        intel = {"backend": "vulkan", "vendor": "Intel", "name": "Intel(R) Arc(TM) A770 Graphics"}
        devices = ["Vulkan0: NVIDIA GeForce RTX 3080 Ti (1 MiB)", "Vulkan1: Intel(R) Arc(TM) A770 Graphics (DG2) (1 MiB)"]
        self.assertEqual(a.pick_vulkan_device(devices, intel), "Vulkan1")

    def test_single_device_or_other_backend_needs_no_pin(self):
        amd = {"backend": "vulkan", "vendor": "AMD", "name": "AMD Radeon RX 5700 XT"}
        self.assertIsNone(a.pick_vulkan_device(VULKAN_DEVICES[:1], amd))
        self.assertIsNone(a.pick_vulkan_device(VULKAN_DEVICES, dict(amd, backend="cuda")))
        self.assertIsNone(a.pick_vulkan_device([], amd))

    def test_unmatched_name_is_not_guessed(self):
        other = {"backend": "vulkan", "vendor": "Intel", "name": "Something Else"}
        self.assertIsNone(a.pick_vulkan_device(VULKAN_DEVICES, other))

    def test_server_command_pins_the_device_and_rejects_odd_ids(self):
        cmd = a.server_command("llama-server", "m.gguf", 18090, "k", "alias", "vulkan", device="Vulkan0")
        self.assertEqual(cmd[cmd.index("--device") + 1], "Vulkan0")
        self.assertNotIn("--device", a.server_command("llama-server", "m.gguf", 18090, "k", "alias", "vulkan"))
        self.assertNotIn("--device", a.server_command("llama-server", "m.gguf", 18090, "k", "alias", "vulkan",
                                                      device="Vulkan0;rm -rf"))
        self.assertNotIn("--device", a.server_command("llama-server", "m.gguf", 18090, "k", "alias", "cpu",
                                                      device="Vulkan0"))


class VerifyAmdGpu(unittest.TestCase):
    def server(self, text):
        d = tempfile.mkdtemp()
        log = Path(d) / "s.log"
        log.write_text(text)
        return SimpleNamespace(log_path=log, process=SimpleNamespace(pid=1))

    LOG = "load_tensors: offloaded 27/27 layers to GPU\nload_tensors:      Vulkan0 model buffer size =   763.00 MiB\n"

    def test_amd_on_gpu_needs_a_log_buffer_and_a_vram_rise(self):
        gpu = {"vendor": "AMD", "name": "AMD Radeon RX 5700 XT", "backend": "vulkan"}
        server = self.server(self.LOG)
        with patch("gpu_link_autosetup.vram_used_mb", return_value=6303 + 1100):
            on, ev = a.verify_gpu(server, gpu, devices=["Vulkan0: AMD"], used_before=6303)
        self.assertTrue(on)
        self.assertTrue(any("rose 1100 MiB" in e for e in ev))
        with patch("gpu_link_autosetup.vram_used_mb", return_value=6303 + 20):
            on, _ = a.verify_gpu(server, gpu, devices=["Vulkan0: AMD"], used_before=6303)
        self.assertFalse(on)  # the buffer is in the log but nothing landed on the chosen card

    def test_small_model_needs_a_proportionally_small_rise(self):
        gpu = {"vendor": "AMD", "name": "AMD", "backend": "vulkan"}
        tiny = self.server("load_tensors:      Vulkan0 model buffer size =    90.00 MiB\n")
        with patch("gpu_link_autosetup.vram_used_mb", return_value=1000 + 120):
            self.assertTrue(a.verify_gpu(tiny, gpu, devices=["Vulkan0: AMD"], used_before=1000)[0])
        with patch("gpu_link_autosetup.vram_used_mb", return_value=1000 + 10):
            self.assertFalse(a.verify_gpu(tiny, gpu, devices=["Vulkan0: AMD"], used_before=1000)[0])

    def test_amd_without_a_measurement_falls_back_to_the_log(self):
        gpu = {"vendor": "AMD", "name": "AMD", "backend": "vulkan"}
        with patch("gpu_link_autosetup.vram_used_mb", return_value=None):
            on, _ = a.verify_gpu(self.server(self.LOG), gpu, devices=["Vulkan0: AMD"], used_before=None)
        self.assertTrue(on)


class ForcedPinning(unittest.TestCase):
    def test_forced_vendor_that_cannot_be_pinned_refuses_to_start(self):
        gpu = {"vendor": "AMD", "name": "AMD Radeon RX 5700 XT", "backend": "vulkan", "forced": "amd", "budget_mb": 100}
        info = {"gpu": gpu, "runtime": {"type": "llama-server"}, "model": {"choice": "local"}, "extras": []}
        args = SimpleNamespace(runtime_dir=Path("/nonexistent"), no_download=True)
        devices = ["Vulkan0: Something Else (1 MiB)", "Vulkan1: Another Card (1 MiB)"]
        with patch.object(a, "ensure_llama_server", return_value=Path("/x/llama-server")), \
                patch.object(a, "runtime_env", return_value={}), patch.object(a, "probe_binary", return_value=(True, "v")), \
                patch.object(a, "list_devices", return_value=devices):
            with self.assertRaises(RuntimeError) as ctx:
                a.start_runtime(args, info)
        self.assertIn("none matched", str(ctx.exception))


class OldNvidiaDriver(unittest.TestCase):
    """Driver < 580 on Windows must get the CUDA 12.4 build; < 551 the Vulkan build."""

    def detect(self, driver, system="Windows", environ=None):
        smi = f"NVIDIA GeForce RTX 3080 Ti, 12288, 4229, {driver}\n"
        run = windows_runner(smi=smi)
        return a.detect_gpu(run, system, "AMD64" if system == "Windows" else "x86_64", which_smi,
                            only="auto", environ=environ or {})

    def test_driver_table_on_windows(self):
        table = {"610.60": "win-cuda-13.5-x64", "580.00": "win-cuda-13.5-x64", "579.99": "win-cuda-12.4-x64",
                 "566.36": "win-cuda-12.4-x64", "551.61": "win-cuda-12.4-x64", "550.0": "win-cuda-12.4-x64",
                 "546.33": None, "531.0": None}
        for driver, expected in table.items():
            self.assertEqual(a.cuda_variant("Windows", driver), expected, driver)

    def test_old_driver_branch_asks_for_cuda_12_4_zip_and_cudart(self):
        gpu = self.detect("566.36")
        self.assertEqual((gpu["backend"], gpu["cuda_variant"]), ("cuda", "win-cuda-12.4-x64"))
        self.assertEqual(a.llama_asset("Windows", "AMD64", gpu),
                         ("win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"))

    def test_driver_older_than_cuda_12_4_falls_back_to_vulkan_on_the_nvidia_card(self):
        gpu = self.detect("535.98")
        self.assertEqual((gpu["backend"], gpu["vendor"], gpu["cuda_variant"]), ("vulkan", "NVIDIA", None))
        self.assertEqual(a.llama_asset("Windows", "AMD64", gpu)[0], "win-vulkan-x64.zip")

    def test_fake_driver_hook_selects_the_branch_and_records_that_it_is_fake(self):
        gpu = self.detect("610.60", environ={a.FAKE_DRIVER_ENV: "551.61"})
        self.assertEqual(gpu["cuda_variant"], "win-cuda-12.4-x64")
        self.assertEqual((gpu["driver"], gpu["driver_real"], gpu["driver_faked"]), ("551.61", "610.60", True))
        self.assertEqual(self.detect("610.60", environ={a.FAKE_DRIVER_ENV: "530.1"})["backend"], "vulkan")

    def test_fake_driver_hook_ignores_junk_and_is_off_by_default(self):
        for junk in ("", "abc", "551.61; calc", "-1", "5.5.5.5.5", " "):
            gpu = self.detect("610.60", environ={a.FAKE_DRIVER_ENV: junk})
            self.assertEqual(gpu["cuda_variant"], "win-cuda-13.5-x64", junk)
            self.assertNotIn("driver_faked", gpu)
        self.assertIsNone(a.fake_driver_version({}))
        self.assertEqual(a.fake_driver_version({a.FAKE_DRIVER_ENV: " 560.94 "}), "560.94")

    def test_fake_driver_hook_does_nothing_for_amd_only(self):
        run = windows_runner()
        gpu = a.detect_gpu(run, "Windows", "AMD64", which_smi, only="amd", environ={a.FAKE_DRIVER_ENV: "551.61"})
        self.assertEqual(gpu["vendor"], "AMD")
        self.assertNotIn("driver_faked", gpu)

    def test_linux_old_driver_uses_vulkan(self):
        gpu = self.detect("560.35", system="Linux")
        self.assertEqual(gpu["backend"], "vulkan")

    def test_budget_for_the_old_driver_branch_is_unchanged(self):
        gpu = self.detect("566.36")
        self.assertEqual(gpu["budget_mb"], 4229 - a.VRAM_MARGIN_MB)


class NothingFits(unittest.TestCase):
    """The AMD card on the test PC had 1.8 GB free: a 1.7 GB local file must not beat the 0.8 GB catalog model."""

    def local(self, *sizes):
        return [{"path": f"/m/m{s}.gguf", "name": f"m{s}.gguf", "size_mb": s} for s in sizes]

    def test_picks_the_small_catalog_model_over_a_big_local_one_when_nothing_fits(self):
        choice, entry = a.pick_model(1333, self.local(1760, 3000))
        self.assertEqual((choice, entry["file"]), ("download", "gemma-3-1b-it-Q4_K_M.gguf"))

    def test_keeps_a_local_file_about_as_small_as_the_catalog_one(self):
        self.assertEqual(a.pick_model(100, self.local(900, 3000))[1]["size_mb"], 900)
        self.assertEqual(a.pick_model(100, self.local(700))[1]["size_mb"], 700)

    def test_a_local_model_that_fits_is_still_preferred(self):
        choice, entry = a.pick_model(3000, self.local(1000))
        self.assertEqual((choice, entry["size_mb"]), ("local", 1000))


class RuntimeVariantChoice(unittest.TestCase):
    """A cached runtime of another variant must not be reused (found on the test PC: a cached Vulkan build was
    used for the CUDA 12.4 plan and split the model over both GPUs)."""
    CUDA124 = {"backend": "cuda", "vendor": "NVIDIA", "cuda_variant": "win-cuda-12.4-x64"}
    VULKAN = {"backend": "vulkan", "vendor": "AMD"}

    def runtime(self, root, *folders):
        for folder in folders:
            exe = root / folder / a._exe("llama-server")
            exe.parent.mkdir(parents=True)
            exe.write_text("x")
        return root

    def find(self, root, gpu, system="Windows"):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPOS_LLAMA_SERVER", None)
            return a.find_llama_server(root, which=lambda _: None, gpu=gpu, system=system, machine="AMD64")

    def test_uses_the_folder_for_this_gpus_variant(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.runtime(Path(d), "llama-b12682-win-cuda-12.4-x64", "llama-b12682-win-vulkan-x64",
                                "llama-b12682-win-cuda-13.5-x64")
            self.assertEqual(self.find(root, self.CUDA124).parent.name, "llama-b12682-win-cuda-12.4-x64")
            self.assertEqual(self.find(root, self.VULKAN).parent.name, "llama-b12682-win-vulkan-x64")

    def test_ignores_a_cached_runtime_of_another_variant_so_the_right_one_is_downloaded(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.runtime(Path(d), "llama-b12682-win-vulkan-x64")
            self.assertIsNone(self.find(root, self.CUDA124))

    def test_accepts_a_hand_placed_runtime_and_the_old_behavior_without_a_gpu(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.runtime(Path(d), "my-llama-build")
            self.assertEqual(self.find(root, self.CUDA124).parent.name, "my-llama-build")
        with tempfile.TemporaryDirectory() as d:
            root = self.runtime(Path(d), "llama-b12682-win-vulkan-x64")
            self.assertEqual(self.find(root, None).parent.name, "llama-b12682-win-vulkan-x64")

    def test_an_older_tag_of_the_same_variant_is_still_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.runtime(Path(d), "llama-b12000-win-vulkan-x64")
            self.assertEqual(self.find(root, self.VULKAN).parent.name, "llama-b12000-win-vulkan-x64")

    def test_ensure_downloads_the_right_variant_instead_of_reusing_the_wrong_one(self):
        with tempfile.TemporaryDirectory() as d:
            root = self.runtime(Path(d), "llama-b12682-win-vulkan-x64")
            with self.assertRaises(RuntimeError) as ctx:
                a.ensure_llama_server(root, self.CUDA124, system="Windows", machine="AMD64", allow_download=False)
            self.assertIn("downloads are disabled", str(ctx.exception))


class Arguments(unittest.TestCase):
    def test_gpu_flag_and_env_default(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(a.GPU_ENV, None)
            self.assertEqual(a.arguments([]).gpu, "auto")
            self.assertEqual(a.arguments(["--gpu", "amd"]).gpu, "amd")
        with patch.dict(os.environ, {a.GPU_ENV: "amd"}):
            self.assertEqual(a.arguments([]).gpu, "amd")
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            a.arguments(["--gpu", "bogus"])

    def test_plan_passes_the_choice_to_detection(self):
        args = a.arguments(["--gpu", "amd", "--own-server", "--no-download"])
        with patch("gpu_link_autosetup.detect_gpu", return_value={
                "vendor": "AMD", "name": "AMD", "backend": "vulkan", "budget_mb": 100, "total_mb": None,
                "free_mb": None, "driver": ""}) as det:
            with patch("gpu_link_autosetup.scan_local_ggufs", return_value=[]):
                a.plan(args, runner=windows_runner())
        self.assertEqual(det.call_args.kwargs["only"], "amd")


if __name__ == "__main__":
    unittest.main()

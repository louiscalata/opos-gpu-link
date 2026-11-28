# SPDX-License-Identifier: Apache-2.0
"""Unit tests for plug-and-play detection and model fit. No network, no GPU, no adb."""
import contextlib
import io
import os
import sys
import tarfile
import subprocess
import tempfile
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gpu_link_autosetup as a  # noqa: E402
from gpu_link_worker import proto  # noqa: E402


def runner_for(table):
    """table maps the command's first two words (or first word) to stdout text or None."""
    calls = []

    def run(cmd, **kwargs):
        calls.append((list(cmd), kwargs.get("env")))
        name = Path(cmd[0]).name
        key2 = (name, cmd[1] if len(cmd) > 1 else "")
        out = table.get(key2, table.get(name))
        if out is None:
            return SimpleNamespace(returncode=1, stdout=b"")
        return SimpleNamespace(returncode=0, stdout=out.encode())
    run.calls = calls
    return run


def which_only(*names):
    return lambda n: f"/usr/bin/{n}" if n in names else None


SMI_5080 = "NVIDIA GeForce RTX 5080, 16303, 10065, 595.99.02\n"


class GpuDetection(unittest.TestCase):
    def test_nvidia_uses_free_vram_and_cuda_128_on_linux(self):
        run = runner_for({"nvidia-smi": SMI_5080})
        gpu = a.detect_gpu(run, "Linux", "x86_64", which_only("nvidia-smi"))
        self.assertEqual(gpu["backend"], "cuda")
        self.assertEqual(gpu["cuda_variant"], "ubuntu-cuda-12.8-x64")
        self.assertEqual(gpu["free_mb"], 10065)
        self.assertEqual(gpu["budget_mb"], 10065 - a.VRAM_MARGIN_MB)

    def test_multi_gpu_picks_most_free(self):
        out = "RTX 3060, 12288, 2000, 580.1\nRTX 4090, 24564, 23000, 580.1\n"
        gpu = a.detect_gpu(runner_for({"nvidia-smi": out}), "Windows", "AMD64", which_only("nvidia-smi"))
        self.assertEqual(gpu["name"], "RTX 4090")
        self.assertEqual(gpu["cuda_variant"], "win-cuda-13.5-x64")

    def test_old_nvidia_driver_falls_back_to_vulkan(self):
        gpu = a.detect_gpu(runner_for({"nvidia-smi": "GTX 1080, 8192, 7000, 535.10\n"}),
                           "Linux", "x86_64", which_only("nvidia-smi"))
        self.assertEqual(gpu["backend"], "vulkan")
        self.assertEqual(a.cuda_variant("Windows", "552.1"), "win-cuda-12.4-x64")
        self.assertIsNone(a.cuda_variant("Windows", "531.0"))
        self.assertIsNone(a.cuda_variant("Linux", "garbage"))

    def test_apple_silicon_is_metal_with_ram_budget(self):
        run = runner_for({("sysctl", "-n"): str(48 * 1024 ** 3)})
        gpu = a.detect_gpu(run, "Darwin", "arm64", which_only())
        self.assertEqual(gpu["backend"], "metal")
        self.assertEqual(gpu["budget_mb"], int(49152 * 0.70) - 1024)
        small = a.detect_gpu(runner_for({("sysctl", "-n"): str(16 * 1024 ** 3)}), "Darwin", "arm64", which_only())
        self.assertEqual(small["budget_mb"], int(16384 * 0.60) - 1024)

    def test_amd_linux_is_vulkan_and_no_gpu_is_cpu(self):
        lspci = "03:00.0 VGA compatible controller: Advanced Micro Devices, Inc. [AMD/ATI] Navi 31\n"
        gpu = a.detect_gpu(runner_for({"lspci": lspci}), "Linux", "x86_64", which_only())
        self.assertEqual((gpu["vendor"], gpu["backend"]), ("AMD", "vulkan"))
        cpu = a.detect_gpu(runner_for({}), "Linux", "x86_64", which_only())
        self.assertEqual(cpu["backend"], "cpu")

    def test_runtime_asset_names_match_llama_cpp_release(self):
        cuda = {"backend": "cuda", "cuda_variant": "ubuntu-cuda-12.8-x64"}
        self.assertEqual(a.llama_asset("Linux", "x86_64", cuda),
                         ("ubuntu-cuda-12.8-x64.tar.gz", "cudart-llama-{tag}-bin-ubuntu-cuda-12.8-x64.tar.gz"))
        self.assertEqual(a.llama_asset("Darwin", "arm64", {"backend": "metal"})[0], "macos-arm64.tar.gz")
        self.assertEqual(a.llama_asset("Windows", "AMD64", {"backend": "cuda", "cuda_variant": "win-cuda-12.4-x64"}),
                         ("win-cuda-12.4-x64.zip", "cudart-llama-bin-win-cuda-12.4-x64.zip"))
        self.assertEqual(a.llama_asset("Linux", "x86_64", {"backend": "vulkan"})[0], "ubuntu-vulkan-x64.tar.gz")
        self.assertEqual(a.llama_asset("Windows", "AMD64", {"backend": "cpu"})[0], "win-cpu-x64.zip")


class ModelFit(unittest.TestCase):
    def local(self, *sizes):
        return [{"path": f"/m/m{s}.gguf", "name": f"m{s}.gguf", "size_mb": s} for s in sizes]

    def test_need_includes_cache_and_overhead(self):
        self.assertGreater(a.need_mb(2375), 2375 + 800)
        self.assertLess(a.need_mb(2375), 4200)

    def test_largest_local_that_fits(self):
        choice, entry = a.pick_model(9300, self.local(2400, 4460, 20000))
        self.assertEqual((choice, entry["size_mb"]), ("local", 4460))

    def test_downloads_catalog_when_nothing_local_fits(self):
        choice, entry = a.pick_model(9300, self.local(20000))
        self.assertEqual(choice, "download")
        self.assertEqual(entry["file"], "gemma-3-4b-it-Q4_K_M.gguf")  # 12B needs ~10.2 GB

    def test_vram_tiers(self):
        tiers = {3500: "gemma-3-1b", 6000: "gemma-3-4b", 12000: "gemma-3-12b", 24000: "gemma-3-27b",
                 22000: "gemma-3-12b", 40000: "gemma-3-27b"}
        for budget, expected in tiers.items():
            self.assertTrue(a.pick_model(budget, [])[1]["file"].startswith(expected), budget)

    def test_tiny_local_prefers_much_bigger_catalog(self):
        choice, entry = a.pick_model(12000, self.local(470))
        self.assertEqual((choice, entry["file"]), ("download", "gemma-3-12b-it-Q4_K_M.gguf"))

    def test_nothing_fits_uses_smallest(self):
        self.assertEqual(a.pick_model(100, self.local(3000, 900))[1]["size_mb"], 900)
        self.assertEqual(a.pick_model(100, [])[1]["file"], "gemma-3-1b-it-Q4_K_M.gguf")

    def test_demo_cap_prefers_snappy_model_on_big_memory(self):
        choice, entry = a.pick_model(44000, self.local(20965, 4460), max_mb=10000)
        self.assertEqual((choice, entry["size_mb"]), ("local", 4460))
        self.assertEqual(a.pick_model(44000, [], max_mb=10000)[1]["file"], "gemma-3-12b-it-Q4_K_M.gguf")
        self.assertEqual(a.pick_model(44000, self.local(20965), max_mb=10000)[1]["file"], "gemma-3-12b-it-Q4_K_M.gguf")

    def test_draft_and_speculative_files_are_skipped(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("dflash-Muse-30B-Q4_K_M.gguf", "model-draft.gguf", "real-chat-Q4.gguf"):
                with open(Path(d) / name, "wb") as f:
                    f.truncate(300 * 1024 * 1024)
            self.assertEqual([m["name"] for m in a.scan_local_ggufs([d])], ["real-chat-Q4.gguf"])

    def test_prefer_overrides_fit(self):
        self.assertEqual(a.pick_model(100, self.local(3000, 900), prefer="m3000")[1]["size_mb"], 3000)

    def test_scan_skips_projectors_shards_and_small_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "pub" / "x").mkdir(parents=True)
            for name, mb in (("good-Q4.gguf", 300), ("mmproj-x.gguf", 300), ("tiny.gguf", 10),
                             ("big-00002-of-00003.gguf", 300), ("notes.txt", 300)):
                with open(root / "pub" / "x" / name, "wb") as f:
                    f.truncate(mb * 1024 * 1024)
            os.symlink(root / "pub" / "x" / "good-Q4.gguf", root / "alias.gguf")
            found = a.scan_local_ggufs([root, root / "missing"])
            self.assertEqual([f["name"] for f in found], ["alias.gguf"] if found[0]["name"] == "alias.gguf"
                             else ["good-Q4.gguf"])
            self.assertEqual(found[0]["size_mb"], 300)

    def test_server_model_choice(self):
        backend = {"models": ["text-embedding-nomic", "gemma-3-27b-it", "qwen/qwen3-4b", "lfm3-1.7b"]}
        self.assertEqual(a.choose_server_model(backend, 9000), "qwen/qwen3-4b")
        self.assertEqual(a.choose_server_model(backend, 40000), "gemma-3-27b-it")
        self.assertEqual(a.choose_server_model(backend, 500), "lfm3-1.7b")
        self.assertIsNone(a.choose_server_model({"models": ["nomic-embed"]}, 9000))
        self.assertEqual(a.estimate_params_b("Qwen2.5-0.5B-Instruct"), 0.5)
        self.assertIsNone(a.estimate_params_b("llama"))


class ExistingServers(unittest.TestCase):
    def test_protected_ports_never_probed_without_lmstudio_owner(self):
        seen = {}

        def discover(urls, allow):
            seen["urls"], seen["allow"] = urls, allow
            return []
        a.find_existing_servers(discover=discover, owner=lambda port: "llama-server")
        self.assertFalse(seen["allow"])
        for url in seen["urls"]:
            port = int(url.rsplit(":", 1)[1])
            self.assertNotIn(port, a.gpu_link_discover.PROTECTED_PORTS)

    def test_lmstudio_on_1234_is_used_unless_strict(self):
        seen = {}

        def discover(urls, allow):
            seen["urls"], seen["allow"] = urls, allow
            return [{"url": "http://127.0.0.1:1234", "kind": "LM Studio", "models": ["m"]},
                    {"url": "http://127.0.0.1:8000", "kind": "Ollama", "models": ["m"]}]
        found = a.find_existing_servers(discover=discover, owner=lambda port: "LM Studio")
        self.assertTrue(seen["allow"])
        self.assertEqual(seen["urls"][0], "http://127.0.0.1:1234")
        self.assertEqual([b["kind"] for b in found], ["LM Studio"])
        a.find_existing_servers(strict_ports=True, discover=discover,
                                owner=lambda port: self.fail("strict mode must not inspect ports"))
        self.assertFalse(seen["allow"])
        self.assertNotIn("http://127.0.0.1:1234", seen["urls"])

    def test_owner_check_reads_process_name_only(self):
        run = runner_for({"lsof": "p123\ncLM Studio Helper\n"})
        self.assertEqual(a.port_owner_name(1234, run, "Darwin"), "LM Studio Helper")
        cmd = run.calls[0][0]
        self.assertIn("-Fc", cmd)  # command name field only, never argv
        self.assertTrue(a.looks_like_lmstudio("LM Studio Helper"))
        self.assertFalse(a.looks_like_lmstudio("llama-server"))

    def test_protected_flags_for_companion(self):
        url = "http://127.0.0.1:1234/v1/chat/completions"
        self.assertEqual(a.protected_flags(url), ["--probe-url", url, "--allow-protected-port"])
        self.assertEqual(a.protected_flags("http://127.0.0.1:18090/v1/chat/completions"), [])


class RuntimeAndGpuVerify(unittest.TestCase):
    def test_ld_library_path_includes_runtime_and_cudart(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "llama-b1-ubuntu-cuda-12"
            (root / "llama-b1").mkdir(parents=True)
            (root / "cudart-llama-b1-bin-ubuntu-cuda-12.8-x64").mkdir()
            (root / "llama-b1" / "llama-server").write_text("")
            (root / "llama-b1" / "libggml-cuda.so").write_text("")
            (root / "cudart-llama-b1-bin-ubuntu-cuda-12.8-x64" / "libcudart.so.12").write_text("")
            env = a.runtime_env(root / "llama-b1" / "llama-server", "Linux", {"LD_LIBRARY_PATH": "/old"})
            parts = env["LD_LIBRARY_PATH"].split(os.pathsep)
            self.assertIn(str(root / "llama-b1"), parts)
            self.assertIn(str(root / "cudart-llama-b1-bin-ubuntu-cuda-12.8-x64"), parts)
            self.assertEqual(parts[-1], "/old")
            self.assertIn("PATH", a.runtime_env(root / "llama-b1" / "llama-server", "Windows", {}))

    def test_offload_log_parsing(self):
        log = ("load_tensors: offloaded 35/35 layers to GPU\n"
               "load_tensors:        CUDA0 model buffer size =  2320.00 MiB\n")
        info = a.parse_offload_log(log)
        self.assertEqual(info["layers"], (35, 35))
        self.assertEqual(info["gpu_buffers_mib"], [("CUDA0", 2320.0)])
        self.assertTrue(a.parse_offload_log("ggml_cuda_init: failed to initialize CUDA")["cpu_fallback_hint"])

    @patch.object(a.platform, "system", return_value="Linux")
    def test_verify_gpu_reports_cpu_when_no_vram_and_no_offload(self, _system):
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "s.log"
            log.write_text("load_tensors: CPU model buffer size = 2300 MiB\n")
            server = SimpleNamespace(log_path=log, process=SimpleNamespace(pid=42))
            gpu = {"vendor": "NVIDIA", "backend": "cuda"}
            on, ev = a.verify_gpu(server, gpu, runner_for({"nvidia-smi": "99, 6000\n"}))
            self.assertFalse(on)
            self.assertIn("nvidia-smi: 0 MiB for this server", ev)
            on, ev = a.verify_gpu(server, gpu, runner_for({"nvidia-smi": "42, 3100\n"}))
            self.assertTrue(on)  # VRAM held by this PID is proof even if the log is terse
            log.write_text("offloaded 35/35 layers to GPU\nCUDA0 model buffer size =  2368.00 MiB\n")
            on, ev = a.verify_gpu(server, gpu, runner_for({"nvidia-smi": "42, 3100\n"}), ["CUDA0: RTX"])
            self.assertTrue(on)

    @patch.object(a.platform, "system", return_value="Windows")
    def test_windows_unknown_per_process_vram_uses_total_vram_rise(self, _system):
        # Windows (WDDM) shows no per-process VRAM: pid missing or "[N/A]". That is unknown, not zero.
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "s.log"
            log.write_text("offloaded 35/35 layers to GPU\nCUDA0 model buffer size =  2368.00 MiB\n")
            server = SimpleNamespace(log_path=log, process=SimpleNamespace(pid=42))
            gpu = {"vendor": "NVIDIA", "backend": "cuda"}
            self.assertIsNone(a.nvidia_pid_memory(42, runner_for({"nvidia-smi": "99, 6000\n"})))
            self.assertIsNone(a.nvidia_pid_memory(42, runner_for({"nvidia-smi": "42, [N/A]\n"})))
            both = {"nvidia-smi": "99, 6000\n"}
            # total used is queried with --query-gpu: fake it
            with patch.object(a, "nvidia_total_used_mb", return_value=10600):
                on, ev = a.verify_gpu(server, gpu, runner_for(both), used_before=8050)
            self.assertTrue(on)
            self.assertTrue(any("total VRAM rose 2550 MiB" in line for line in ev))
            with patch.object(a, "nvidia_total_used_mb", return_value=8100):
                on, ev = a.verify_gpu(server, gpu, runner_for(both), used_before=8050)
            self.assertFalse(on)  # buffer line says GPU but no VRAM was taken: not proof
            on, _ = a.verify_gpu(server, gpu, runner_for(both))  # no baseline: fall back to the log
            self.assertTrue(on)

    @patch.object(a.platform, "system", return_value="Linux")
    def test_offloaded_layers_alone_is_not_gpu_proof(self, _system):
        # Real RTX 5080 negative control: no LD_LIBRARY_PATH -> CPU, yet the log says 35/35.
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "s.log"
            log.write_text("load_tensors: offloaded 35/35 layers to GPU\n"
                           "load_tensors:   CPU_Mapped model buffer size =  2368.00 MiB\n")
            server = SimpleNamespace(log_path=log, process=SimpleNamespace(pid=42))
            on, ev = a.verify_gpu(server, {"vendor": "NVIDIA", "backend": "cuda"},
                                  runner_for({"nvidia-smi": "99, 6000\n"}), devices=[])
            self.assertFalse(on)
            self.assertIn("llama.cpp listed no GPU devices", ev)
            on, _ = a.verify_gpu(server, {"vendor": "Apple", "backend": "metal"}, runner_for({}))
            self.assertFalse(on)  # non-NVIDIA needs a GPU buffer line in the log

    def test_list_devices_parses_gpu_rows(self):
        out = "Available devices:\n  CUDA0: NVIDIA GeForce RTX 5080 (16303 MiB, 10000 MiB free)\n"
        self.assertEqual(a.list_devices(Path("/x/llama-server"), {}, runner_for({"llama-server": out})),
                         ["CUDA0: NVIDIA GeForce RTX 5080 (16303 MiB, 10000 MiB free)"])
        self.assertEqual(a.list_devices(Path("/x/llama-server"), {}, runner_for({"llama-server": "Available devices:\n"})), [])

    def test_choose_port_skips_forbidden_and_busy(self):
        busy = {18090}
        self.assertEqual(a.choose_port(18090, 5, free=lambda p: p not in busy), 18091)
        self.assertEqual(a.choose_port(1234, 5, free=lambda p: True), 1238)  # 1237 is protected too
        self.assertEqual(a.choose_port(18090, 5, free=lambda p: True, taken=(18090, 18091)), 18092)
        with self.assertRaises(RuntimeError):
            a.choose_port(18090, 2, free=lambda p: False)

    def test_port_range_is_checked_before_a_socket_is_opened(self):
        free = Mock(return_value=True)
        for start, span in ((0, 10), (-1, 10), (65527, 10), (65535, 2), (18090, 0)):
            with self.subTest(start=start, span=span), self.assertRaisesRegex(ValueError, "1 and 65535"):
                a.choose_port(start, span, free=free)
        free.assert_not_called()
        self.assertEqual(a.choose_port(65526, 10, free=free), 65526)

    def test_invalid_starting_port_has_a_plain_setup_message(self):
        for value in ("-1", "0", "65527", "65536"):
            with self.subTest(value=value), contextlib.redirect_stderr(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as raised:
                    a.arguments(["--port", value])
                self.assertEqual(raised.exception.code, 2)
                self.assertIn("--port must be between 1 and 65526", output.getvalue())
                self.assertNotIn("Traceback", output.getvalue())
        self.assertEqual(a.arguments(["--port", "65526"]).port, 65526)

    def test_extract_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as d:
            archive = Path(d) / "bad.tar.gz"
            with tarfile.open(archive, "w:gz") as t:
                data = b"x"
                info = tarfile.TarInfo("../escape")
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
            with self.assertRaises(RuntimeError):
                a.extract(archive, Path(d) / "out")
            self.assertFalse((Path(d) / "escape").exists())


class PhoneDetection(unittest.TestCase):
    def state(self, text):
        return a.phone_state(Path("adb"), runner_for({"adb": "List of devices attached\n" + text}))

    def test_states(self):
        self.assertEqual(self.state(""), ("none", None))
        self.assertEqual(self.state("R5CX\tunauthorized usb:1-1 transport_id:3\n"), ("unauthorized", "R5CX"))
        self.assertEqual(self.state("R5CX\tno permissions (missing udev rules?) usb:1-1\n"),
                         ("no permissions", "R5CX"))
        self.assertEqual(self.state("R5CX\toffline usb:1-1\n"), ("offline", "R5CX"))
        self.assertEqual(self.state("R5CX\tdevice usb:1-1 model:SM_F741U\n"), ("device", "R5CX"))
        self.assertEqual(self.state("192.0.2.5:5555\tdevice\nemulator-5554\tdevice\n"), ("none", None))
        self.assertEqual(self.state("A\tdevice usb:1\nB\tdevice usb:2\n"), ("many", None))
        self.assertEqual(self.state("A\tunauthorized usb:1\nB\tdevice usb:2\n"), ("device", "B"))

    def test_failed_usb_tools_check_is_not_reported_as_no_phone(self):
        self.assertEqual(a.phone_state(Path("adb"), runner_for({})), ("usb unavailable", None))

    def test_wait_shows_allow_text_then_returns_serial(self):
        outputs = iter(["", "R5CX\tunauthorized usb:1\n", "R5CX\tunauthorized usb:1\n", "R5CX\tdevice usb:1\n"])

        def run(cmd, **kwargs):
            if cmd[1] == "start-server":
                return SimpleNamespace(returncode=0, stdout=b"")
            return SimpleNamespace(returncode=0, stdout=("List of devices attached\n" + next(outputs)).encode())
        buffer = io.StringIO()
        with patch("sys.stdout", buffer):
            serial = a.wait_for_phone(Path("adb"), run, sleep=lambda s: None)
        text = buffer.getvalue()
        self.assertEqual(serial, "R5CX")
        self.assertIn("Plug in the USB-C cable", text)
        self.assertEqual(text.count("Allow USB debugging on the phone"), 1)  # shown once per state change

    def test_adb_found_before_download(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "adb"
            fake.write_text("")
            quiet = _adb_lsof_runner(returncode=1)
            with patch.object(a, "adb_candidates", return_value=[Path(d) / "nope", fake]):
                self.assertEqual(a.ensure_adb(Path(d), allow_download=False, runner=quiet, system="linux"), fake.resolve())
            with patch.object(a, "adb_candidates", return_value=[]):
                with self.assertRaises(RuntimeError):
                    a.ensure_adb(Path(d), allow_download=False, runner=quiet, system="linux")


def _adb_lsof_runner(*, listen="", txt="", returncode=0):
    def run(cmd, **kwargs):
        joined = " ".join(cmd)
        if cmd and cmd[0] == "lsof" and "-iTCP:5037" in joined:
            rc = 0 if listen else returncode
            return SimpleNamespace(returncode=rc, stdout=listen.encode())
        if cmd and cmd[0] == "lsof" and "-p" in cmd:
            return SimpleNamespace(returncode=0 if txt else 1, stdout=txt.encode())
        return SimpleNamespace(returncode=1, stdout=b"")
    return run


def _adb_powershell_runner(*, lines="", returncode=0, explode=False):
    def run(cmd, **kwargs):
        if explode:
            raise OSError("powershell missing")
        if cmd and cmd[0] == "powershell.exe":
            return SimpleNamespace(returncode=returncode, stdout=lines.encode())
        return SimpleNamespace(returncode=1, stdout=b"")
    return run


class AdbServerBinary(unittest.TestCase):
    def _two_adbs(self, root: Path, name: str = "adb"):
        path_adb = root / "path" / name
        server_adb = root / "server" / name
        path_adb.parent.mkdir()
        server_adb.parent.mkdir()
        path_adb.write_text("")
        server_adb.write_text("")
        path_adb.chmod(0o755)
        server_adb.chmod(0o755)
        return path_adb, server_adb

    def test_prefers_running_server_binary_over_path(self):
        with tempfile.TemporaryDirectory() as d:
            path_adb, server_adb = self._two_adbs(Path(d))
            runner = _adb_lsof_runner(
                listen="p4242\nn127.0.0.1:5037\n",
                txt="n%s\n" % server_adb,
            )
            notes = []
            got = a.prefer_running_adb_server(path_adb, runner=runner, announce=notes.append, system="linux")
            self.assertEqual(got, server_adb.resolve())
            self.assertTrue(notes)
            self.assertEqual(notes, ["Using USB tools already running on this computer."])
            self.assertNotIn(str(server_adb), notes[0])

    def test_keeps_selected_when_no_server(self):
        with tempfile.TemporaryDirectory() as d:
            path_adb, _server = self._two_adbs(Path(d))
            got = a.prefer_running_adb_server(
                path_adb, runner=_adb_lsof_runner(returncode=1), announce=lambda *_: None,
                system="linux")
            self.assertEqual(got, path_adb.resolve())

    def test_keeps_selected_when_it_is_the_server(self):
        with tempfile.TemporaryDirectory() as d:
            path_adb, _server = self._two_adbs(Path(d))
            runner = _adb_lsof_runner(
                listen="p7\nn127.0.0.1:5037\n",
                txt="n%s\n" % path_adb,
            )
            notes = []
            got = a.prefer_running_adb_server(path_adb, runner=runner, announce=notes.append, system="linux")
            self.assertEqual(got, path_adb.resolve())
            self.assertEqual(notes, [])

    def test_ensure_adb_explicit_follows_the_running_server(self):
        with tempfile.TemporaryDirectory() as d:
            path_adb, server_adb = self._two_adbs(Path(d))
            runner = _adb_lsof_runner(
                listen="p4242\nn127.0.0.1:5037\n",
                txt="n%s\n" % server_adb,
            )
            got = a.ensure_adb(Path(d), explicit=str(path_adb), allow_download=False, runner=runner, system="linux")
            self.assertEqual(got, server_adb.resolve())

    def test_refuses_non_loopback_adb_server(self):
        with tempfile.TemporaryDirectory() as d:
            path_adb, server_adb = self._two_adbs(Path(d))
            runner = _adb_lsof_runner(
                listen="p4242\nn192.0.2.5:5037\n",
                txt="n%s\n" % server_adb,
            )
            got = a.prefer_running_adb_server(path_adb, runner=runner, announce=lambda *_: None, system="linux")
            self.assertEqual(got, path_adb.resolve())

    def test_accepts_ipv6_loopback_lsof_and_ignores_f_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path_adb, server_adb = self._two_adbs(Path(d))
            runner = _adb_lsof_runner(
                listen="p9\nf4\nn[::1]:5037\n",
                txt="n%s\n" % server_adb,
            )
            got = a.running_adb_server_executable(runner=runner, system="linux")
            self.assertEqual(got, server_adb.resolve())

    def test_refuses_wildcard_bind_and_two_listener_pids(self):
        with tempfile.TemporaryDirectory() as d:
            _path_adb, server_adb = self._two_adbs(Path(d))
            wildcard = _adb_lsof_runner(listen="p1\nn*:5037\n", txt="n%s\n" % server_adb)
            two = _adb_lsof_runner(
                listen="p1\nn127.0.0.1:5037\np2\nn127.0.0.1:5037\n",
                txt="n%s\n" % server_adb,
            )
            self.assertIsNone(a.running_adb_server_executable(runner=wildcard, system="linux"))
            self.assertIsNone(a.running_adb_server_executable(runner=two, system="linux"))

    def test_lsof_missing_returns_none(self):
        def boom(*_args, **_kwargs):
            raise OSError("lsof missing")
        self.assertIsNone(a.running_adb_server_executable(runner=boom, system="linux"))

    def test_windows_detects_loopback_server_via_powershell(self):
        with tempfile.TemporaryDirectory() as d:
            path_adb, server_adb = self._two_adbs(Path(d), name="adb.exe")
            runner = _adb_powershell_runner(lines="127.0.0.1|%s\n" % server_adb)
            got = a.running_adb_server_executable(runner=runner, system="win32")
            self.assertEqual(got, server_adb.resolve())
            notes = []
            preferred = a.prefer_running_adb_server(
                path_adb, runner=runner, announce=notes.append, system="win32")
            self.assertEqual(preferred, server_adb.resolve())
            self.assertTrue(notes)

    def test_windows_accepts_dual_stack_same_binary_and_refuses_non_loopback(self):
        with tempfile.TemporaryDirectory() as d:
            _path_adb, server_adb = self._two_adbs(Path(d), name="adb.exe")
            both = _adb_powershell_runner(
                lines="127.0.0.1|%s\n::1|%s\n" % (server_adb, server_adb))
            self.assertEqual(
                a.running_adb_server_executable(runner=both, system="win32"),
                server_adb.resolve())
            bad = _adb_powershell_runner(lines="192.0.2.5|%s\n" % server_adb)
            self.assertIsNone(a.running_adb_server_executable(runner=bad, system="win32"))
            missing = _adb_powershell_runner(explode=True)
            self.assertIsNone(a.running_adb_server_executable(runner=missing, system="win32"))

    def test_ensure_adb_uses_running_server_when_no_candidate_instead_of_not_found(self):
        with tempfile.TemporaryDirectory() as d:
            _path_adb, server_adb = self._two_adbs(Path(d))
            runner = _adb_lsof_runner(
                listen="p4242\nn127.0.0.1:5037\n",
                txt="n%s\n" % server_adb,
            )
            with patch.object(a, "adb_candidates", return_value=[]):
                got = a.ensure_adb(Path(d), allow_download=False, runner=runner, system="linux")
            self.assertEqual(got, server_adb.resolve())

    def test_ensure_adb_does_not_download_when_a_server_is_already_running(self):
        with tempfile.TemporaryDirectory() as d:
            _path_adb, server_adb = self._two_adbs(Path(d))
            runner = _adb_lsof_runner(
                listen="p4242\nn127.0.0.1:5037\n",
                txt="n%s\n" % server_adb,
            )
            def no_download(*_args, **_kwargs):
                raise AssertionError("should not download when a server is running")
            with patch.object(a, "adb_candidates", return_value=[]), \
                    patch.object(a, "download", no_download):
                got = a.ensure_adb(Path(d), allow_download=True, runner=runner, system="linux")
            self.assertEqual(got, server_adb.resolve())

    def test_bare_adb_name_uses_which_not_cwd(self):
        with tempfile.TemporaryDirectory() as d:
            path_adb, server_adb = self._two_adbs(Path(d))
            # Without a live server, "adb" must resolve via PATH, not <cwd>/adb.
            with patch.object(a.shutil, "which", return_value=str(path_adb)):
                got = a.prefer_running_adb_server(
                    "adb", runner=_adb_lsof_runner(returncode=1), announce=lambda *_: None,
                    system="linux")
            self.assertEqual(got, path_adb.resolve())
            runner = _adb_lsof_runner(
                listen="p3\nn127.0.0.1:5037\n",
                txt="n%s\n" % server_adb,
            )
            notes = []
            with patch.object(a.shutil, "which", return_value=str(path_adb)):
                got = a.prefer_running_adb_server("adb", runner=runner, announce=notes.append, system="linux")
            self.assertEqual(got, server_adb.resolve())
            self.assertTrue(notes)

    def test_explicit_missing_path_without_a_server_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            missing = Path(d) / "no-such-adb"
            with self.assertRaises(RuntimeError):
                a.ensure_adb(Path(d), explicit=str(missing), allow_download=False,
                             runner=_adb_lsof_runner(returncode=1), system="linux")



    def test_bare_adb_does_not_use_a_cwd_file_when_not_on_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cwd_adb = root / "adb"
            cwd_adb.write_text("")
            cwd_adb.chmod(0o755)
            with patch.object(a.shutil, "which", return_value=None):
                import os
                old = os.getcwd()
                try:
                    os.chdir(d)
                    self.assertTrue((root / "adb").is_file())
                    self.assertIsNone(a.resolve_adb_path("adb"))
                    with self.assertRaises(RuntimeError):
                        a.ensure_adb(root, explicit="adb", allow_download=False,
                                     runner=_adb_lsof_runner(returncode=1), system="linux")
                finally:
                    os.chdir(old)

    def test_explicit_relative_adb_stays_an_absolute_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            local = root / "adb"
            local.write_text("")
            local.chmod(0o755)
            import os
            old = os.getcwd()
            try:
                os.chdir(d)
                got = a.resolve_adb_path("./adb")
                self.assertEqual(got, local.resolve())
                selected = a.ensure_adb(root, explicit="./adb", allow_download=False,
                                        runner=_adb_lsof_runner(returncode=1), system="linux")
                self.assertEqual(selected, local.resolve())
                self.assertTrue(selected.is_absolute())
            finally:
                os.chdir(old)

    def test_bare_adb_not_on_path_adopts_a_running_server(self):
        with tempfile.TemporaryDirectory() as d:
            _path_adb, server_adb = self._two_adbs(Path(d))
            runner = _adb_lsof_runner(
                listen="p4242\nn127.0.0.1:5037\n",
                txt="n%s\n" % server_adb,
            )
            with patch.object(a.shutil, "which", return_value=None):
                got = a.ensure_adb(Path(d), explicit="adb", allow_download=False,
                                   runner=runner, system="linux")
            self.assertEqual(got, server_adb.resolve())

    def test_explicit_missing_path_is_not_replaced_by_a_running_server(self):
        with tempfile.TemporaryDirectory() as d:
            _path_adb, server_adb = self._two_adbs(Path(d))
            runner = _adb_lsof_runner(
                listen="p4242\nn127.0.0.1:5037\n",
                txt="n%s\n" % server_adb,
            )
            missing = Path(d) / "no-such-adb"
            with self.assertRaises(RuntimeError):
                a.ensure_adb(Path(d), explicit=str(missing), allow_download=False,
                             runner=runner, system="linux")

    def test_windows_accepts_uppercase_executable_name(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            server = root / "server" / "ADB.EXE"
            server.parent.mkdir()
            server.write_text("")
            server.chmod(0o755)
            runner = _adb_powershell_runner(lines="127.0.0.1|%s\n" % server)
            got = a.running_adb_server_executable(runner=runner, system="win32")
            self.assertEqual(got, server.resolve())



class Labels(unittest.TestCase):
    def test_label_is_valid_for_phone(self):
        for name in ("NVIDIA GeForce RTX 5080", "Apple M5 Pro", "AMD Radeon(TM) RX 7900 XTX", "", "!!!"):
            label = a.safe_label({"name": name}, "Linux")
            self.assertTrue(proto.valid_label(label), (name, label))
        self.assertEqual(a.safe_label({"name": "NVIDIA GeForce RTX 5080"}, "Windows"), "RTX 5080 PC")
        for system in ("Darwin", "Linux", "Windows"):
            for model in ("MacBook Pro", "Mac mini", "", "MacBook Pro (16-inch, 2026) !!"):
                for name in ("Apple M5 Pro", "AMD Radeon Pro 5500M", "", "!!!", "AMD Radeon RX 7900 XTX -9",
                             "A" * 40, "x" * 23 + " -y"):
                    label = a.safe_label({"name": name}, system, model)
                    self.assertTrue(proto.valid_label(label), (system, model, name, label))

    def test_wire_label_rule_matches_the_protocol(self):
        self.assertEqual(a.WIRE_LABEL.pattern, proto._LABEL.pattern)

    def test_a_mac_is_named_as_a_mac(self):
        self.assertEqual(a.safe_label({"name": "Apple M5 Pro"}, "Darwin", "MacBook Pro"), "M5 Pro MacBook Pro")
        self.assertEqual(a.safe_label({"name": "Apple M4"}, "Darwin", "Mac mini"), "M4 Mac mini")
        self.assertEqual(a.safe_label({"name": "AMD Radeon Pro 5500M"}, "Darwin", "MacBook Pro"),
                         "MacBook Pro")  # too long with the GPU name; still a Mac
        self.assertEqual(a.safe_label({"name": "AMD Radeon Pro 5500M"}, "Darwin", "iMac"),
                         "AMD Radeon Pro 5500M Mac")
        self.assertEqual(a.safe_label({"name": "Apple M5 Pro"}, "Darwin", ""), "M5 Pro Mac")
        self.assertEqual(a.safe_label({}, "Darwin", "MacBook Air"), "MacBook Air")
        self.assertEqual(a.safe_label({"name": "X" * 12}, "Darwin", "MacBook Pro"), "X" * 12 + " MacBook Pro")  # 24
        self.assertEqual(a.safe_label({"name": "X" * 13}, "Darwin", "MacBook Pro"), "X" * 13 + " MacBook")  # 25 -> noun
        self.assertEqual(a.safe_label({"name": "X" * 20}, "Darwin", "MacBook Pro"), "MacBook Pro")

    def test_non_mac_never_asks_for_a_model_name_and_truncation_keeps_the_rule(self):
        with patch.object(a, "mac_model_name", side_effect=AssertionError("not on a PC")):
            self.assertEqual(a.safe_label({"name": "AMD Radeon RX 7900 XTX -9"}, "Linux"), "AMD Radeon RX 7900 XTX")
            self.assertEqual(a.safe_label({"name": "!!!"}, "Windows"), "GPU PC")

    def test_darwin_default_reads_the_model_name_once(self):
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            return SimpleNamespace(returncode=0, stdout='{"SPHardwareDataType": [{"machine_name": "MacBook Air"}]}')
        with patch.object(a, "_MODEL_NAME_CACHE", []), patch.object(a.subprocess, "run", side_effect=run):
            self.assertEqual(a.safe_label({"name": "Apple M4"}, "Darwin"), "M4 MacBook Air")
            self.assertEqual(a.safe_label({"name": "Apple M4"}, "Darwin"), "M4 MacBook Air")
        self.assertEqual(calls, [[a.MAC_PROFILER, "-json", "SPHardwareDataType"]])

    def test_mac_model_name_reads_only_machine_name(self):
        out = '{"SPHardwareDataType": [{"machine_name": "MacBook Pro", "chip_type": "Apple M5 Pro"}]}'
        calls = []

        def runner(argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout=out)
        self.assertEqual(a.mac_model_name(runner), "MacBook Pro")
        self.assertIs(calls[0][1]["stdin"], subprocess.DEVNULL)
        self.assertLessEqual(calls[0][1]["timeout"], 5)

        def broken(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, 5)
        self.assertEqual(a.mac_model_name(broken), "")
        self.assertEqual(a.mac_model_name(lambda *x, **k: SimpleNamespace(returncode=1, stdout=out)), "")
        for bad in (None, "", "not json", "[]", '{"SPHardwareDataType": []}', '{"SPHardwareDataType": [{}]}',
                    '{"SPHardwareDataType": [{"machine_name": 7}]}', '{"SPHardwareDataType": "x"}',
                    '{"SPHardwareDataType": {"a": 1}}', '"text"'):
            self.assertEqual(a.mac_model_name(lambda *x, b=bad, **k: SimpleNamespace(returncode=0, stdout=b)), "", bad)

        def missing(argv, **kwargs):
            raise OSError("no profiler")
        self.assertEqual(a.mac_model_name(missing), "")
        self.assertEqual(a.safe_label({"name": "!!!"}, "Darwin", "!!!"), "Mac")


class ChatOverCoder(unittest.TestCase):
    def test_coder_models_are_not_auto_picked_even_when_bigger(self):
        local = [{"path": "/m/qwen2.5-coder-7b.gguf", "name": "qwen2.5-coder-7b.gguf", "size_mb": 4466},
                 {"path": "/m/gemma3-4b.gguf", "name": "gemma3-4b.gguf", "size_mb": 2380}]
        self.assertEqual(a.pick_model(8834, local)[1]["name"], "gemma3-4b.gguf")
        self.assertEqual(a.pick_model(8834, local, prefer="coder")[1]["name"], "qwen2.5-coder-7b.gguf")
        self.assertEqual(a.pick_model(8834, local[:1])[0], "download")  # catalog chat model beats a coder file

    def test_coder_name_detection(self):
        for name in ("Qwen2.5-Coder-7B", "codellama-13b", "starcoder2-3b", "devstral-small", "deepseek-math-7b"):
            self.assertTrue(a.is_coder(name), name)
        for name in ("gemma-3-4b-it", "Qwen3-4B", "decode-model", "LFM2-1.2B", "Llama-3.2-3B-Instruct"):
            self.assertFalse(a.is_coder(name), name)

    def test_existing_server_prefers_chat_model(self):
        backend = {"models": ["qwen2.5-coder-14b", "gemma-3-4b-it"]}
        self.assertEqual(a.choose_server_model(backend, 20000), "gemma-3-4b-it")


class ExtraLanes(unittest.TestCase):
    MAIN = {"path": "/m/g4.gguf", "name": "gemma-3-4b.gguf", "size_mb": 2375, "maker": "Google"}

    def test_two_extras_from_other_makers_when_memory_allows(self):
        extras = a.pick_extras(9000, self.MAIN, [])
        self.assertEqual([e["maker"] for e in extras], ["Qwen", "Liquid AI"])
        self.assertTrue(all(e["size_mb"] <= self.MAIN["size_mb"] * 1.1 for e in extras))

    def test_memory_limits_the_extras(self):
        self.assertEqual(len(a.pick_extras(a.need_mb(2381) + 10, self.MAIN, [])), 1)
        self.assertEqual(a.pick_extras(500, self.MAIN, []), [])
        self.assertEqual(len(a.pick_extras(9000, self.MAIN, [], limit=1)), 1)

    def test_packs_two_smaller_extras_instead_of_one_large(self):
        """5080-like leftover: Qwen3-4B fits alone; Qwen3-1.7B + LFM2-1.2B fill both lanes."""
        left = a.need_mb(1749) + a.need_mb(697) + 50  # 4913 + headroom, still below 4B+LFM
        self.assertLess(left, a.need_mb(2381) + a.need_mb(697))
        extras = a.pick_extras(left, self.MAIN, [])
        self.assertEqual([e["file"] for e in extras], ["Qwen3-1.7B-Q8_0.gguf", "LFM2-1.2B-Q4_K_M.gguf"])
        self.assertEqual([e["maker"] for e in extras], ["Qwen", "Liquid AI"])

    def test_5080_three_lane_fits_default_budget_with_512_margin(self):
        """Live 5080 numbers (receipts/5080-three-lane/): peak 13688/16303, 2152 still free.

        Conservative need_mb for Gemma 3 4B + Qwen3-1.7B + LFM2-1.2B was 107 MB over
        free-768, so the e2e had to pass --budget-mb 9100. A 512 MB margin fits that
        set automatically and is still well under the 2152 MiB left at peak (need_mb
        over-estimated actual VRAM rise, 8941 vs ~7436).
        """
        self.assertEqual(a.VRAM_MARGIN_MB, 512)
        gemma = next(r for r in a.pins.MODELS if r["file"].startswith("gemma-3-4b"))
        qwen = next(r for r in a.pins.MODELS if r["file"] == "Qwen3-1.7B-Q8_0.gguf")
        lfm = next(r for r in a.pins.MODELS if r["file"] == "LFM2-1.2B-Q4_K_M.gguf")
        need = a.need_mb(gemma["size"] // (1024 * 1024)) + a.need_mb(qwen["size"] // (1024 * 1024)) + a.need_mb(lfm["size"] // (1024 * 1024))
        free_mb, peak_used, total = 9602, 13688, 16303
        self.assertGreater(need, free_mb - 768)
        self.assertLessEqual(need, free_mb - a.VRAM_MARGIN_MB)
        # The live local gemma3-4b was slightly larger (need 4028, total 8941) than the catalog pin (4016).
        self.assertGreater(8941, free_mb - 768)
        self.assertLessEqual(8941, free_mb - a.VRAM_MARGIN_MB)
        self.assertGreaterEqual(total - peak_used, a.VRAM_MARGIN_MB)
        extras = a.pick_extras(free_mb - a.VRAM_MARGIN_MB - a.need_mb(gemma["size"] // (1024 * 1024)), self.MAIN, [])
        self.assertEqual([e["file"] for e in extras], ["Qwen3-1.7B-Q8_0.gguf", "LFM2-1.2B-Q4_K_M.gguf"])

    def test_same_maker_and_coder_files_are_skipped_local_preferred(self):
        local = [{"path": "/m/gemma-3-1b.gguf", "name": "gemma-3-1b.gguf", "size_mb": 800, "maker": "Google"},
                 {"path": "/m/qwen2.5-coder-3b.gguf", "name": "qwen2.5-coder-3b.gguf", "size_mb": 2000, "maker": "Qwen"},
                 {"path": "/m/lfm2-1.2b.gguf", "name": "lfm2-1.2b.gguf", "size_mb": 700, "maker": "Liquid AI"}]
        extras = a.pick_extras(9000, self.MAIN, local)
        self.assertEqual([e["maker"] for e in extras], ["Liquid AI", "Qwen"])
        self.assertEqual(extras[0]["choice"], "local")  # a local file avoids a download
        self.assertEqual(extras[1]["choice"], "download")  # coder file skipped -> Qwen3 from catalog

    def test_cpu_only_gets_no_extras_and_flags_parse(self):
        args = a.arguments(["--no-extras", "--detect-only"])
        self.assertTrue(args.no_extras)
        self.assertEqual(a.arguments(["--extras", "1"]).extras, 1)

    def test_companion_args_carry_lanes_and_parse(self):
        import opos_gpu_link as link
        rt = a.Runtime()
        rt.lanes = [{"id": "opos-gpu-link", "url": "http://127.0.0.1:18090/v1/chat/completions", "label": "Gemma 3 4B", "maker": "Google"},
                    {"id": "opos-gpu-link-2", "url": "http://127.0.0.1:18091/v1/chat/completions", "label": "Qwen3 4B", "maker": "Qwen"},
                    {"id": "opos-gpu-link-3", "url": "http://127.0.0.1:18092/v1/chat/completions", "label": "LFM2 2.6B", "maker": "Liquid AI"}]
        with patch.object(a, "mac_model_name", return_value="MacBook Pro"):  # never the real profiler
            argv = a.companion_args(a.arguments([]), rt, {"gpu": {"name": "NVIDIA GeForce RTX 5080"}}, Path("adb"), "R5CX")
        parsed = link.arguments(argv)
        self.assertEqual([m["id"] for m in parsed.extra_models], ["opos-gpu-link-2", "opos-gpu-link-3"])
        self.assertEqual([(m["label"], m["maker"]) for m in parsed.extra_models],
                         [("Qwen3 4B", "Qwen (Alibaba)"),
                          ("LFM2 2.6B (baseline)", "Liquid AI")])
        self.assertEqual(parsed.model_servers["opos-gpu-link-3"], "http://127.0.0.1:18092/v1/chat/completions")
        self.assertEqual(parsed.model, "opos-gpu-link")
        with self.assertRaises(SystemExit), patch("sys.stderr", io.StringIO()):
            link.arguments(argv + ["--model-server", "x=http://127.0.0.1:1236/v1/chat/completions"])


class Security(unittest.TestCase):
    def test_server_command_is_loopback_keyfile_cors_and_has_no_key(self):
        key = a.new_key()
        path = a.write_key_file(key)
        try:
            cmd = a.server_command(Path("/x/llama-server"), "/m.gguf", 18090, path, "opos-gpu-link", "cuda")
            self.assertEqual(cmd[cmd.index("--host") + 1], "127.0.0.1")
            self.assertEqual(cmd[cmd.index("--api-key-file") + 1], str(path))
            self.assertEqual(cmd[cmd.index("--cors-origins") + 1], "localhost")
            self.assertEqual(cmd[cmd.index("-lv") + 1], "4")
            self.assertNotIn("--api-key", cmd)
            self.assertFalse(any(key in part for part in cmd))
            self.assertEqual(path.read_text().strip(), key)
            if os.name != "nt":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                self.assertEqual(path.parent.stat().st_mode & 0o777, 0o700)
        finally:
            import shutil
            shutil.rmtree(path.parent, ignore_errors=True)
        self.assertGreaterEqual(len(key), 40)
        self.assertNotEqual(key, a.new_key())

    def test_runtime_env_drops_the_key_and_drop_key_file_deletes_it(self):
        env = a.runtime_env(Path("/x/llama-server"), "Linux", {a.KEY_ENV: "secret", "A": "1"})
        self.assertNotIn(a.KEY_ENV, env)
        rt = a.Runtime()
        rt.key_file = a.write_key_file("k")
        folder = rt.key_file.parent
        rt.drop_key_file()
        self.assertFalse(folder.exists())

    def test_companion_sends_bearer_from_environment_only(self):
        from gpu_link_worker import server_auth_headers
        with patch.dict(os.environ, {a.KEY_ENV: "abc123"}):
            self.assertEqual(server_auth_headers(), {"Authorization": "Bearer abc123"})
        with patch.dict(os.environ, {a.KEY_ENV: "bad\nkey"}):
            self.assertEqual(server_auth_headers(), {})
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(server_auth_headers(), {})

    def test_preflight_and_stream_requests_include_bearer(self):
        import http.client
        import gpu_link_worker
        import opos_gpu_link as link
        seen, connections = [], []
        case = self

        class Wire:
            def settimeout(self, _timeout):
                pass

            def shutdown(self, _how):
                pass

            def close(self):
                pass

        class Response:
            status = 200

            def __init__(self):
                event = {"model": "m", "choices": [{"index": 0, "delta": {"content": "OK"},
                                                    "finish_reason": "stop"}]}
                self.lines = iter([b"data: " + json.dumps(event).encode() + b"\n", b"data: [DONE]\n"])

            def getheader(self, name, default=None):
                return "text/event-stream" if name == "Content-Type" else default

            def readline(self, _limit):
                return next(self.lines, b"")

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                pass

        class Conn:
            def __init__(self, host, port, timeout):
                case.assertEqual((host, port, timeout), ("127.0.0.1", 38124, 2))
                self.sock = Wire()
                self.closed = False
                connections.append(self)

            def connect(self):
                pass

            def request(self, method, target, body=None, headers=None):
                seen.append((method, target, json.loads(body), headers))

            def getresponse(self):
                return Response()

            def close(self):
                self.closed = True

        url = "http://127.0.0.1:38124/v1/chat/completions"
        with patch.dict(os.environ, {a.KEY_ENV: "k3y"}), patch.object(http.client, "HTTPConnection", Conn):
            self.assertTrue(link.model_server_preflight(url, "m"))
            source = gpu_link_worker.ServerSource({"question": "A question", "partial": ""}, url, "m")
            try:
                source.worker.join(2)
                self.assertFalse(source.worker.is_alive())
                self.assertEqual(source.snapshot()[0], b"OK")
                self.assertFalse(source.snapshot()[-1])
            finally:
                source.close()
        self.assertEqual(len(seen), 2)
        self.assertEqual([body.get("max_tokens") for _, _, body, _ in seen], [1, None])
        for method, target, body, headers in seen:
            self.assertEqual((method, target), ("POST", "/v1/chat/completions"))
            self.assertEqual(headers["Authorization"], "Bearer k3y")
            self.assertNotIn("k3y", json.dumps(body))
        self.assertTrue(all(connection.closed for connection in connections))


class Pinning(unittest.TestCase):
    def serve(self, d, data):
        src = Path(d) / "src.bin"
        src.write_bytes(data)
        return src.as_uri()

    def test_download_accepts_match_and_rejects_mismatch(self):
        import hashlib
        data = os.urandom(5000)
        good = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as d, patch("builtins.print"):
            url = self.serve(d, data)
            dest = Path(d) / "out" / "f.bin"
            self.assertEqual(a.download(url, dest, "t", good), dest)
            self.assertTrue(a._sidecar(dest).exists())
            self.assertEqual(a.download(url, dest, "t", good), dest)  # cached via sidecar
            with self.assertRaises(RuntimeError) as ctx:
                a.download(url, Path(d) / "out" / "g.bin", "t", "0" * 64)
            self.assertIn("mismatch", str(ctx.exception))
            self.assertFalse((Path(d) / "out" / "g.bin").exists())
            self.assertFalse((Path(d) / "out" / "g.bin.part").exists())
            with self.assertRaises(RuntimeError):
                a.download(url, Path(d) / "out" / "h.bin", "t", "")  # unpinned refused

    def test_tampered_cached_file_is_not_trusted(self):
        import hashlib
        data = b"a" * 4096
        sha = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as d, patch("builtins.print"):
            url = self.serve(d, data)
            dest = Path(d) / "f.bin"
            a.download(url, dest, "t", sha)
            dest.write_bytes(b"b" * 4096)  # same size, different bytes
            # Windows file times tick about every 15 ms, so a rewrite right after the download can keep the same
            # mtime and the sidecar would still match. A real edit happens later; model that.
            before = dest.stat().st_mtime_ns
            os.utime(dest, ns=(before, before + 2_000_000_000))
            self.assertFalse(a.verified_file(dest, sha))
            a.download(url, dest, "t", sha)  # re-fetched
            self.assertEqual(dest.read_bytes(), data)

    def test_every_download_the_launcher_can_make_is_pinned(self):
        import re as _re
        sha = _re.compile(r"[0-9a-f]{64}")
        for name, pin in a.pins.LLAMA.items():
            self.assertRegex(pin["sha256"], sha, name)
            self.assertGreater(pin["size"], 1_000_000, name)
        for os_name, pin in a.pins.PLATFORM_TOOLS.items():
            self.assertRegex(pin["sha256"], sha)
            self.assertIn("r37.0.3", pin["url"])
        for row in a.pins.MODELS:
            self.assertRegex(row["sha256"], sha, row["file"])
        for system, machine, gpu in (("Linux", "x86_64", {"backend": "cuda", "cuda_variant": "ubuntu-cuda-12.8-x64"}),
                                     ("Linux", "x86_64", {"backend": "vulkan"}), ("Linux", "x86_64", {"backend": "cpu"}),
                                     ("Darwin", "arm64", {"backend": "metal"}), ("Darwin", "x86_64", {"backend": "metal"}),
                                     ("Windows", "AMD64", {"backend": "cuda", "cuda_variant": "win-cuda-13.5-x64"}),
                                     ("Windows", "AMD64", {"backend": "cuda", "cuda_variant": "win-cuda-12.4-x64"}),
                                     ("Windows", "AMD64", {"backend": "vulkan"}), ("Windows", "AMD64", {"backend": "cpu"})):
            suffix, cudart = a.llama_asset(system, machine, gpu)
            self.assertIn(f"llama-{a.LLAMA_TAG}-bin-{suffix}", a.pins.LLAMA, (system, gpu))
            if cudart:
                self.assertIn(cudart.format(tag=a.LLAMA_TAG), a.pins.LLAMA)

    def test_catalog_entries_have_pins_sizes_and_makers(self):
        for row in a.pins.MODELS:
            self.assertIn(row["role"], ("main", "extra"))
            self.assertTrue(row["file"].endswith(".gguf"))
            self.assertGreater(row["size"], 500_000_000)
        mains = [r for r in a.pins.MODELS if r["role"] == "main"]
        self.assertEqual([r["size"] for r in mains], sorted((r["size"] for r in mains), reverse=True))


class DataDirAndBundle(unittest.TestCase):
    def test_data_dir_rules(self):
        with patch.dict(os.environ):
            os.environ.pop("OPOS_GPU_LINK_HOME", None)
            self.assertEqual(a.data_dir(), a.HERE)
        with patch.dict(os.environ, {"OPOS_GPU_LINK_HOME": "/tmp/x"}):
            self.assertEqual(a.data_dir(), Path("/tmp/x"))
        with patch.dict(os.environ), patch.object(a, "FROZEN", True), patch("platform.system", return_value="Darwin"):
            os.environ.pop("OPOS_GPU_LINK_HOME", None)
            self.assertIn("Application Support", str(a.data_dir()))
        with patch.dict(os.environ, {"XDG_DATA_HOME": "/tmp/xdg"}), patch.object(a, "FROZEN", True), \
                patch("platform.system", return_value="Linux"):
            os.environ.pop("OPOS_GPU_LINK_HOME", None)
            self.assertEqual(a.data_dir(), Path("/tmp/xdg/opos-gpu-link"))

    def test_bundled_adb_is_after_system_adb(self):
        paths = a.adb_candidates(home="/nonexistent", which=lambda n: "/usr/bin/adb")
        self.assertEqual(paths[0], Path("/usr/bin/adb"))
        self.assertEqual(paths[-1].parent.name, "adb")
        self.assertEqual(paths[-1].parent.parent.name, "bundled")

    def test_probe_binary_reports_illegal_instruction(self):
        def run(cmd, **kw):
            return SimpleNamespace(returncode=-4, stdout=b"")
        ok, detail = a.probe_binary(Path("/x/llama-server"), {}, run)
        self.assertFalse(ok)
        self.assertIn("AVX", detail)
        ok, detail = a.probe_binary(Path("/x/llama-server"), {}, lambda c, **k: SimpleNamespace(returncode=0, stdout=b"version: 1 (abc)\n"))
        self.assertEqual((ok, detail), (True, "version: 1 (abc)"))

    def test_probe_binary_explains_loader_failures(self):
        text = (b"dyld[1]: Symbol not found: (_cblas_sgemm$NEWLAPACK$ILP64)\n  Referenced from: x\n")
        ok, detail = a.probe_binary(Path("/x/llama-server"), {}, lambda c, **k: SimpleNamespace(returncode=134, stdout=text))
        self.assertFalse(ok)
        self.assertIn("too old", detail)
        self.assertIn("_cblas_sgemm", detail)
        ok, detail = a.probe_binary(Path("/x/llama-server"), {}, lambda c, **k: SimpleNamespace(returncode=-6, stdout=b""))
        self.assertEqual((ok, detail), (False, "crashed with code -6"))

    def test_avx_detection(self):
        with patch("platform.machine", return_value="x86_64"):
            run = runner_for({("sysctl", "-n"): "FPU SSE4.2 POPCNT"})
            self.assertFalse(a.cpu_has_avx(run, "Darwin"))
            self.assertTrue(a.cpu_has_avx(runner_for({("sysctl", "-n"): "FPU AVX1.0 SSE4.2"}), "Darwin"))
        with patch("platform.machine", return_value="arm64"):
            self.assertTrue(a.cpu_has_avx(runner_for({}), "Darwin"))

    def test_intel_mac_with_radeon_uses_vram_budget(self):
        sp = "Graphics/Displays:\n  AMD Radeon RX 580:\n      Chipset Model: AMD Radeon RX 580\n      VRAM (Total): 8 GB\n"
        run = runner_for({("sysctl", "-n"): "137438953472", "system_profiler": sp})
        gpu = a.detect_gpu(run, "Darwin", "x86_64", which_only())
        self.assertEqual((gpu["vendor"], gpu["backend"], gpu["total_mb"]), ("AMD", "metal", 8192))
        self.assertEqual(gpu["budget_mb"], 8192 - 1500)

    def test_maker_and_label_guessing(self):
        self.assertEqual(a.maker_of("Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"), "Qwen")
        self.assertEqual(a.maker_of("mystery.gguf"), "Local")
        self.assertEqual(a.maker_of("Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf"), "NVIDIA")
        self.assertEqual(a.maker_of("NVIDIA-Nemotron3-Nano-4B-Q4_K_M.gguf"), "NVIDIA")
        self.assertEqual(a.maker_of("nvidia_Llama-3.1-Nemotron-Nano-4B-v1.1-Q4_K_M.gguf"), "NVIDIA")
        self.assertEqual(a.maker_of("nvidia_AceInstruct-1.5B-Q4_K_M.gguf"), "NVIDIA")
        self.assertEqual(a.label_of("Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf"), "Nemotron 3.5 Bolt")
        self.assertEqual(a.label_of("LFM2-1.2B-Q4_K_M.gguf"), "LFM2 1.2B (baseline)")
        self.assertEqual(a.served_model_label("LFM2 2.6B"), "LFM2 2.6B (baseline)")
        self.assertEqual(a.display_maker("Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf", "Local"), "NVIDIA")
        self.assertEqual(a.display_maker("LFM2-1.2B-Q4_K_M.gguf", "Local"), "Liquid AI")
        self.assertEqual(a.display_maker("Qwen3-4B-Q4_K_M.gguf", "Qwen"), "Qwen (Alibaba)")
        self.assertEqual(a.display_model_label("Qwen3.5-2B_Q4_K_M.gguf"), "Qwen3.5-2B")
        self.assertEqual(a.display_model_label("Granite-4.1-3B_Q4_K_M.gguf"), "Granite 4.1 3B")
        self.assertEqual(a.display_model_label("Nemotron-3.5-Bolt_Q4_K_M.gguf"), "Nemotron 3.5 Bolt")
        self.assertEqual(a.display_model_label("LFM2_1.2B.gguf"), "LFM2 1.2B (baseline)")
        self.assertEqual(a.display_model_label("LFM2"), "LFM2 (baseline)")
        self.assertEqual(a.display_model_label("LFM2 2.6B"), "LFM2 2.6B (baseline)")
        self.assertEqual(a.display_model_label("LFM2 (comparison baseline)"), "LFM2 (baseline)")
        self.assertEqual(a.display_model_label("LFM2.5"), "LFM2.5")
        for source, label, maker in (
            ("LFM2.5B", "LFM2.5B", "Local"),
            ("LFM2.gguf", "LFM2 (baseline)", "Liquid AI"),
            ("LFM2-1.2B", "LFM2 1.2B (baseline)", "Liquid AI"),
        ):
            with self.subTest(source=source):
                self.assertEqual(a.display_model_label(source), label)
                self.assertEqual(a.display_maker(source, "Local"), maker)
        self.assertEqual(a.display_maker("LiquidAI/LFM2-VL", "Local"), "Liquid AI")
        self.assertEqual(a.display_maker("Liquid AI LFM2", "Local"), "Liquid AI")
        self.assertEqual(a.display_maker("LFM2.5", "Local"), "Local")
        fallback = "Qwen3-4B-Q4_K_M.gguf (fallback for Nemotron-3.5-Bolt-E4B)"
        self.assertEqual(a.display_model_label(fallback),
                         "Qwen3-4B-Q4_K_M.gguf (fallback for Nemotron 3.5 Bolt)")
        self.assertEqual(a.display_maker(fallback, "Qwen"), "Qwen (Alibaba)")
        self.assertEqual(a.display_maker("Other.gguf (fallback for Granite-4.1-3B)", "Local"), "Local")
        self.assertEqual(a.display_model_label("unrelated.gguf"), "unrelated.gguf")
        self.assertEqual(a.label_of("Qwen3.8-27B-UD-Q6_K.gguf"), "Qwen3.8-27B")


class GpuOutputCheck(unittest.TestCase):
    def fake_reply(self, reply, status=200, response_body=None):
        """Exercise the request/response contract without opening a socket."""
        seen = {}

        class Connection:
            def __init__(self, host, port, timeout):
                seen["address"] = host, port
                seen["timeout"] = timeout

            def request(self, method, target, body, headers):
                seen["method"], seen["target"] = method, target
                seen["body"] = json.loads(body)
                seen["auth"] = headers.get("Authorization")
                seen["content_type"] = headers.get("Content-Type")

            def getresponse(self):
                body = response_body if response_body is not None else json.dumps(
                    {"choices": [{"message": {"content": reply}}]}).encode()
                return SimpleNamespace(status=status, read=lambda limit: body[:limit])

            def close(self):
                seen["closed"] = True

        replacement = patch("http.client.HTTPConnection", Connection)
        replacement.start()
        self.addCleanup(replacement.stop)
        return 38120, seen

    def test_looks_like_text(self):
        self.assertTrue(a.looks_like_text("Hello there, everyone!"))
        self.assertFalse(a.looks_like_text(""))
        self.assertFalse(a.looks_like_text("\n\n  \n"))
        self.assertFalse(a.looks_like_text("<pad><pad>"))
        self.assertFalse(a.looks_like_text(None))

    def test_good_reply_passes_and_sends_the_key(self):
        port, seen = self.fake_reply("Hello, wonderful audience!")
        with patch.dict(os.environ, {"OPOS_GPU_LINK_REASONING_EFFORT": "none"}):
            self.assertEqual(a.check_lane_output(port, "k3y"), (True, "ok"))
        self.assertEqual(seen["auth"], "Bearer k3y")
        self.assertEqual(seen["address"], ("127.0.0.1", port))
        self.assertEqual((seen["method"], seen["target"]), ("POST", "/v1/chat/completions"))
        self.assertEqual(seen["content_type"], "application/json")
        self.assertEqual(seen["body"], {
            "model": a.ALIAS, "max_tokens": 48, "temperature": 0, "stream": False,
            "messages": [{"role": "user", "content": "Say hello to the audience in one short sentence."}],
            "reasoning_effort": "none", "chat_template_kwargs": {"enable_thinking": False},
        })
        self.assertNotIn("k3y", json.dumps(seen["body"]))
        self.assertTrue(seen["closed"])

    def test_reasoning_effort_override_is_used_for_the_probe(self):
        port, seen = self.fake_reply("Hello, wonderful audience!")
        with patch.dict(os.environ, {"OPOS_GPU_LINK_REASONING_EFFORT": "medium"}):
            self.assertEqual(a.check_lane_output(port, "k"), (True, "ok"))
        self.assertEqual(seen["body"]["reasoning_effort"], "medium")
        self.assertNotIn("chat_template_kwargs", seen["body"])

    def test_default_reasoning_effort_override_is_omitted(self):
        port, seen = self.fake_reply("Hello, wonderful audience!")
        with patch.dict(os.environ, {"OPOS_GPU_LINK_REASONING_EFFORT": "default"}):
            self.assertEqual(a.check_lane_output(port, "k"), (True, "ok"))
        self.assertNotIn("reasoning_effort", seen["body"])
        self.assertNotIn("chat_template_kwargs", seen["body"])

    def test_blank_reply_fails(self):
        port, _ = self.fake_reply("\n\n\n")
        ok, why = a.check_lane_output(port, "k")
        self.assertFalse(ok)
        self.assertIn("no readable words", why)

    def test_hidden_reasoning_does_not_make_a_blank_answer_ready(self):
        body = json.dumps({"choices": [{"message": {
            "content": "", "reasoning_content": "A detailed hidden explanation"
        }}]}).encode()
        port, seen = self.fake_reply("", response_body=body)
        self.assertEqual(a.check_lane_output(port, "k"), (False, "the reply had no readable words"))
        self.assertTrue(seen["closed"])

    def test_visible_answer_is_checked_on_its_own(self):
        body = json.dumps({"choices": [{"message": {
            "content": "Hello to everyone.", "reasoning_content": ["hidden format differs"]
        }}]}).encode()
        port, _ = self.fake_reply("", response_body=body)
        self.assertEqual(a.check_lane_output(port, "k"), (True, "ok"))

    def test_error_and_dead_server_fail(self):
        port, _ = self.fake_reply("x", status=500)
        self.assertEqual(a.check_lane_output(port, "k"), (False, "the model server returned an error"))
        with patch("http.client.HTTPConnection", side_effect=OSError("sensitive backend detail")):
            self.assertEqual(a.check_lane_output(port, "k", timeout=1), (False, "the model server did not answer"))

    def test_malformed_model_replies_fail_plainly_and_close_connection(self):
        for body in (b'not JSON', b'{"choices":null}', b'{"choices":[]}',
                     b'{"choices":[{"message":null}]}',
                     b'{"choices":[{"message":{"content":42}}]}'):
            with self.subTest(body=body):
                port, seen = self.fake_reply("", response_body=body)
                self.assertEqual(a.check_lane_output(port, "k"), (False, "the model reply was invalid"))
                self.assertTrue(seen["closed"])

    def test_oversized_model_reply_is_rejected(self):
        port, seen = self.fake_reply("", response_body=b"x" * 65537)
        self.assertEqual(a.check_lane_output(port, "k"), (False, "the model reply was too long"))
        self.assertTrue(seen["closed"])


class StopReportTests(unittest.TestCase):
    def test_owned_server_stop_failure_changes_the_exit_code(self):
        import opos_gpu_link as link

        args = SimpleNamespace(detect_only=False, prefetch=False, no_phone=False,
                               runtime_dir=Path("/unused/runtime"), adb=None, no_download=True,
                               serial="fixture", data_dir=Path("/unused/data"),
                               models_dir=Path("/unused/models"), keep_server=False)
        info = {"gpu": {"name": "Fixture GPU"}}
        rt = SimpleNamespace(lanes=[], stop=Mock(side_effect=OSError("private stop detail")))
        with contextlib.redirect_stdout(io.StringIO()) as output, \
                patch.object(a, "install_term_handler"), \
                patch.object(a, "plan", return_value=info), \
                patch.object(a, "start_runtime", return_value=rt), \
                patch.object(a, "ensure_adb", return_value=Path("/unused/adb")), \
                patch.object(a, "ready_lines", return_value=[]), \
                patch.object(a, "banner"), \
                patch.object(a, "companion_args", return_value=[]), \
                patch.object(link, "computer_noun", return_value="MacBook"), \
                patch.object(link, "main", return_value=0):
            self.assertEqual(a.run(args), 2)
        rt.stop.assert_called_once_with()
        self.assertIn("Error: Model server did not stop. Check the running server.", output.getvalue())
        self.assertNotIn("private stop detail", output.getvalue())

    def test_requested_stop_with_server_stop_failure_has_failure_exit_code(self):
        import opos_gpu_link as link

        args = SimpleNamespace(detect_only=False, prefetch=False, no_phone=False,
                               runtime_dir=Path("/unused/runtime"), adb=None, no_download=True,
                               serial="fixture", data_dir=Path("/unused/data"),
                               models_dir=Path("/unused/models"), keep_server=False)
        info = {"gpu": {"name": "Fixture GPU"}}
        rt = SimpleNamespace(lanes=[], stop=Mock(side_effect=OSError("private stop detail")))
        with contextlib.redirect_stdout(io.StringIO()) as output, \
                patch.object(a, "install_term_handler"), \
                patch.object(a, "plan", return_value=info), \
                patch.object(a, "start_runtime", return_value=rt), \
                patch.object(a, "ensure_adb", return_value=Path("/unused/adb")), \
                patch.object(a, "ready_lines", return_value=[]), \
                patch.object(a, "banner"), \
                patch.object(a, "companion_args", return_value=[]), \
                patch.object(link, "computer_noun", return_value="MacBook"), \
                patch.object(link, "main", side_effect=a.Terminated):
            self.assertEqual(a.run(args), 2)
        rt.stop.assert_called_once_with()
        self.assertIn("Stopping.", output.getvalue())
        self.assertIn("Error: Model server did not stop. Check the running server.", output.getvalue())
        self.assertNotIn("private stop detail", output.getvalue())


class Rx580OldMacProfile(unittest.TestCase):
    """Mac Pro 5,1 findings: only Q8_0 Qwen2.5/Llama 3.2 answer correctly on the RX 580, and only with -fa off."""
    GPU = {"vendor": "AMD", "name": "AMD Radeon RX 580", "total_mb": 8192, "free_mb": None, "driver": "",
           "backend": "metal", "budget_mb": 6692}

    def args(self):
        return SimpleNamespace(budget_mb=None, own_server=True, strict_ports=False, model_path=None,
                               no_extras=False, extras=2, data_dir=Path("/nonexistent-data"),
                               runtime_dir=Path("/nonexistent-rt"))

    def plan(self, local, gpu=None, system="Darwin", machine="x86_64"):
        gpu = dict(gpu or self.GPU)
        with patch.object(a, "detect_gpu", return_value=gpu), patch.object(a, "scan_local_ggufs", return_value=local), \
                patch.object(a, "find_llama_server", return_value=Path("/x/llama-server")), \
                patch.object(a.platform, "system", return_value=system), \
                patch.object(a.platform, "machine", return_value=machine), \
                patch.object(a, "model_dirs", return_value=[]):
            return a.plan(self.args())

    def test_detects_polaris_on_intel_mac_only(self):
        self.assertEqual(a.gpu_profile(self.GPU, "Darwin", "x86_64", {}), a.PROFILE_RX580)
        self.assertIsNone(a.gpu_profile(self.GPU, "Linux", "x86_64", {}))
        self.assertIsNone(a.gpu_profile(self.GPU, "Darwin", "arm64", {}))
        self.assertIsNone(a.gpu_profile(dict(self.GPU, name="AMD Radeon Pro 5500M"), "Darwin", "x86_64", {}))
        self.assertIsNone(a.gpu_profile(dict(self.GPU, vendor="NVIDIA"), "Darwin", "x86_64", {}))
        for name in ("AMD Radeon RX 570", "Radeon RX 560", "AMD Radeon RX 590"):
            self.assertEqual(a.gpu_profile(dict(self.GPU, name=name), "Darwin", "x86_64", {}), a.PROFILE_RX580)

    def test_env_override(self):
        self.assertEqual(a.gpu_profile({"vendor": "x", "name": "y"}, "Linux", "x86_64", {"OPOS_GPU_LINK_PROFILE": "rx580"}),
                         a.PROFILE_RX580)
        self.assertIsNone(a.gpu_profile(self.GPU, "Darwin", "x86_64", {"OPOS_GPU_LINK_PROFILE": "none"}))

    def test_plan_picks_q8_qwen25_main_and_llama_extra_not_gemma(self):
        info = self.plan([])
        self.assertEqual(info["gpu"]["profile"], a.PROFILE_RX580)
        self.assertEqual(info["model"]["file"], "qwen2.5-1.5b-instruct-q8_0.gguf")
        self.assertEqual([e["file"] for e in info["extras"]], ["Llama-3.2-1B-Instruct-Q8_0.gguf"])
        for entry in [info["model"], *info["extras"]]:
            self.assertEqual(len(entry["sha256"]), 64)
            self.assertIn("q8_0", entry["file"].lower())

    def test_local_files_known_bad_on_this_gpu_are_ignored(self):
        bad = [{"path": "/m/gemma-3-4b-it-Q4_K_M.gguf", "name": "gemma-3-4b-it-Q4_K_M.gguf", "size_mb": 2375, "maker": "Google"},
               {"path": "/m/Qwen3-1.7B-Q8_0.gguf", "name": "Qwen3-1.7B-Q8_0.gguf", "size_mb": 1750, "maker": "Qwen"},
               {"path": "/m/qwen2.5-3b-instruct-q4_k_m.gguf", "name": "qwen2.5-3b-instruct-q4_k_m.gguf", "size_mb": 2000, "maker": "Qwen"}]
        info = self.plan(bad)
        self.assertEqual(info["model"]["choice"], "download")
        good = {"path": "/m/qwen2.5-3b-instruct-q8_0.gguf", "name": "qwen2.5-3b-instruct-q8_0.gguf", "size_mb": 3448, "maker": "Qwen"}
        info = self.plan(bad + [good])
        self.assertEqual((info["model"]["choice"], info["model"]["path"]), ("local", good["path"]))

    def test_other_gpus_are_unchanged(self):
        info = self.plan([], gpu=dict(self.GPU, vendor="Apple", name="Apple M5"))
        self.assertNotIn("profile", info["gpu"])
        self.assertTrue(info["model"]["file"].startswith("gemma-3"))

    def test_server_command_flash_attention_off_only_for_profile(self):
        key = Path("/k")
        on = a.server_command(Path("/x/llama-server"), "/m.gguf", 18090, key, "x", "metal", profile=a.PROFILE_RX580)
        self.assertEqual(on[on.index("-fa") + 1], "off")
        self.assertNotIn("-fa", a.server_command(Path("/x/llama-server"), "/m.gguf", 18090, key, "x", "metal"))

    def test_server_command_keeps_kv_cache_off_the_gpu_only_for_profile(self):
        key = Path("/k")
        on = a.server_command(Path("/x/llama-server"), "/m.gguf", 18090, key, "x", "metal", profile=a.PROFILE_RX580)
        self.assertIn("--no-kv-offload", on)
        self.assertEqual(on[on.index("-fa") + 1], "off")  # the earlier known-good flag stays
        for other in (None, "other-profile"):
            self.assertNotIn("--no-kv-offload", a.server_command(Path("/x/llama-server"), "/m.gguf", 18090, key, "x", "metal", profile=other))
        self.assertNotIn("--no-kv-offload", a.server_command(Path("/x/llama-server"), "/m.gguf", 18090, key, "x", "cuda"))

    def test_moltenvk_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            icd = Path(tmp) / "VulkanSDK" / "macOS" / "share" / "vulkan" / "icd.d"
            icd.mkdir(parents=True)
            (icd / "MoltenVK_icd.json").write_text("{}")
            env = a.moltenvk_env({"PATH": "/bin"}, "Darwin", tmp)
            self.assertEqual(env["VK_ICD_FILENAMES"], str(icd / "MoltenVK_icd.json"))
            self.assertEqual(env["DYLD_LIBRARY_PATH"], str(icd.parents[2] / "lib"))  # not a "/" literal: Windows runs this test too
            mine = {"VK_ICD_FILENAMES": "/mine"}
            self.assertIs(a.moltenvk_env(mine, "Darwin", tmp), mine)  # the caller's own setup wins
            self.assertEqual(a.moltenvk_env({}, "Linux", tmp), {})
            self.assertEqual(a.moltenvk_env({}, "Darwin", tmp + "/none"), {})




class OfflineTests(unittest.TestCase):
    def tearDown(self):
        os.environ.pop(a.OFFLINE_ENV, None)

    def test_offline_sets_no_download(self):
        args = a.arguments(["--offline", "--detect-only"])
        self.assertTrue(args.offline)
        self.assertTrue(args.no_download)
        self.assertTrue(a.is_offline())
        self.assertEqual(os.environ.get(a.OFFLINE_ENV), "1")

    def test_offline_env_sets_no_download(self):
        os.environ[a.OFFLINE_ENV] = "true"
        args = a.arguments(["--detect-only"])
        self.assertTrue(args.offline)
        self.assertTrue(args.no_download)

    def test_no_download_alone_does_not_set_offline_env(self):
        args = a.arguments(["--no-download", "--detect-only"])
        self.assertTrue(args.no_download)
        self.assertFalse(getattr(args, "offline", False))
        self.assertFalse(a.is_offline())

    def test_offline_conflicts_with_prefetch(self):
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as raised:
            a.arguments(["--offline", "--prefetch"])
        self.assertNotEqual(raised.exception.code, 0)
        os.environ[a.OFFLINE_ENV] = "1"
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit) as raised:
            a.arguments(["--prefetch"])
        self.assertNotEqual(raised.exception.code, 0)

    def test_start_script_argv_contract(self):
        self.assertEqual(a.start_script_argv([]), ["--offline"])
        self.assertEqual(a.start_script_argv(["--gpu", "nvidia"]), ["--offline"])
        self.assertEqual(a.start_script_argv(["--prefetch"]), [])
        self.assertEqual(a.start_script_argv(["--offline"]), [])
        self.assertEqual(a.start_script_argv(["--no-download", "--no-phone"]), [])

    def test_offline_blocks_download_without_urlopen(self):
        os.environ[a.OFFLINE_ENV] = "1"
        called = []

        def fake_urlopen(*args, **kwargs):
            called.append((args, kwargs))
            raise AssertionError("urlopen must not be called when --offline")

        dest = Path(tempfile.mkdtemp()) / "file.bin"
        with patch("urllib.request.urlopen", fake_urlopen):
            with self.assertRaises(RuntimeError) as raised:
                a.download("https://example.invalid/file.bin", dest, "test-asset",
                           "ab" * 32, 10)
        self.assertIn("--offline", str(raised.exception))
        self.assertEqual(called, [])
        self.assertFalse(dest.exists())

    def test_ensure_model_offline_no_urlopen(self):
        args = a.arguments(["--offline"])
        self.assertTrue(args.no_download)
        called = []
        with patch("urllib.request.urlopen", lambda *x, **y: called.append(1)):
            with self.assertRaises(RuntimeError) as raised:
                a.ensure_model(
                    "catalog",
                    {"repo": "someone/model", "file": "x.gguf", "label": "X",
                     "sha256": "ab" * 32, "size": 10},
                    Path(tempfile.mkdtemp()),
                    allow_download=not args.no_download,
                )
        self.assertIn("downloads are disabled", str(raised.exception))
        self.assertEqual(called, [])

    def _record_start_script(self, script: Path, extra_args):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            log = tmp / "argv.log"
            wrapper = tmp / "pywrap"
            wrapper.write_text(
                "#!/usr/bin/env python3\n"
                "import os, sys\n"
                "open(os.environ['ARGV_LOG'], 'w').write('\\0'.join(sys.argv[1:]))\n"
            )
            wrapper.chmod(0o755)
            env = os.environ.copy()
            env["OPOS_GPU_LINK_PYTHON"] = str(wrapper)
            env["ARGV_LOG"] = str(log)
            result = subprocess.run(
                ["bash", str(script), *extra_args],
                cwd=script.parent, env=env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            recorded = log.read_text() if log.exists() else ""
            return result, recorded.split("\0") if recorded else []

    @unittest.skipUnless(os.name != "nt", "bash start scripts")
    def test_start_linux_script_prepending_offline(self):
        script = Path(__file__).resolve().parent / "start-linux.sh"
        result, argv = self._record_start_script(script, ["--no-phone"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv[:4], ["-B", "gpu_link_autosetup.py", "--offline", "--no-phone"])

    @unittest.skipUnless(os.name != "nt", "bash start scripts")
    def test_start_linux_script_prefetch_not_offline(self):
        script = Path(__file__).resolve().parent / "start-linux.sh"
        result, argv = self._record_start_script(script, ["--prefetch"])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv, ["-B", "gpu_link_autosetup.py", "--prefetch"])
        self.assertNotIn("--offline", argv)

    @unittest.skipUnless(os.name != "nt", "bash start scripts")
    def test_start_mac_script_prepending_offline(self):
        script = Path(__file__).resolve().parent / "start-mac.command"
        result, argv = self._record_start_script(script, [])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(argv, ["-B", "gpu_link_autosetup.py", "--offline"])

    def test_unfrozen_does_not_default_offline(self):
        self.assertFalse(a.FROZEN)
        args = a.arguments(["--detect-only"])
        self.assertFalse(args.offline)
        self.assertFalse(args.no_download)
        self.assertFalse(a.is_offline())

    def test_frozen_defaults_to_offline(self):
        with patch.object(a, "FROZEN", True):
            self.assertTrue(a.should_default_offline(["--detect-only"], frozen=True))
            args = a.arguments(["--detect-only"])
            self.assertTrue(args.offline)
            self.assertTrue(args.no_download)
            self.assertTrue(a.is_offline())
            self.assertEqual(os.environ.get(a.OFFLINE_ENV), "1")

    def test_frozen_prefetch_does_not_default_offline(self):
        with patch.object(a, "FROZEN", True):
            self.assertFalse(a.should_default_offline(["--prefetch"], frozen=True))
            args = a.arguments(["--prefetch", "--detect-only"])
            self.assertFalse(args.offline)
            self.assertFalse(args.no_download)
            self.assertFalse(a.is_offline())

    def test_frozen_no_download_alone_does_not_set_offline_env(self):
        with patch.object(a, "FROZEN", True):
            self.assertFalse(a.should_default_offline(["--no-download", "--detect-only"], frozen=True))
            args = a.arguments(["--no-download", "--detect-only"])
            self.assertTrue(args.no_download)
            self.assertFalse(args.offline)
            self.assertFalse(a.is_offline())

    def test_frozen_default_blocks_download_without_urlopen(self):
        with patch.object(a, "FROZEN", True):
            args = a.arguments(["--detect-only"])
            self.assertTrue(args.offline)
            called = []

            def fake_urlopen(*a2, **k2):
                called.append((a2, k2))
                raise AssertionError("urlopen must not be called when frozen defaults to --offline")

            dest = Path(tempfile.mkdtemp()) / "file.bin"
            with patch("urllib.request.urlopen", fake_urlopen):
                with self.assertRaises(RuntimeError) as raised:
                    a.download("https://example.invalid/file.bin", dest, "test-asset",
                               "ab" * 32, 10)
            self.assertIn("--offline", str(raised.exception))
            self.assertEqual(called, [])
            self.assertFalse(dest.exists())


class ServedLeadLabelTests(unittest.TestCase):
    def _existing(self, model):
        return {
            "gpu": {"name": "Example GPU", "vendor": "Apple", "backend": "metal", "budget_mb": 8000},
            "runtime": {"type": "existing", "kind": "llama-server",
                        "url": "http://127.0.0.1:18090/v1/chat/completions"},
            "model": model,
        }

    def test_existing_server_publishes_the_served_model_label(self):
        with patch.object(a, "say"):
            rt = a.start_runtime(SimpleNamespace(), self._existing(
                {"id": "opos-gpu-link", "label": "Gemma 4 26B"}))
        self.assertTrue(rt.existing)
        self.assertEqual(rt.lanes[0]["id"], "opos-gpu-link")
        self.assertEqual(rt.lanes[0]["label"], "Gemma 4 26B")
        self.assertEqual(rt.lanes[0]["lead_label"], "Gemma 4 26B")
        self.assertTrue(proto.valid_model_label(rt.lanes[0]["lead_label"]))

    def test_existing_bolt_file_has_a_display_name_and_maker_only(self):
        source = {"id": "opos-gpu-link", "label": "Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf"}
        with patch.object(a, "say"):
            rt = a.start_runtime(SimpleNamespace(), self._existing(source))
        self.assertEqual((rt.lanes[0]["id"], rt.lanes[0]["label"], rt.lanes[0]["maker"]),
                         ("opos-gpu-link", "Nemotron 3.5 Bolt", "NVIDIA"))
        self.assertEqual(source["label"], "Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf")

    def test_existing_server_falls_back_to_the_model_id(self):
        with patch.object(a, "say"):
            rt = a.start_runtime(SimpleNamespace(), self._existing({"id": "opos-gpu-link"}))
        self.assertEqual(rt.lanes[0]["label"], "opos-gpu-link")
        self.assertEqual(rt.lanes[0]["lead_label"], "opos-gpu-link")

    def test_existing_server_uses_served_name_for_maker_after_blank_label(self):
        with patch.object(a, "say"):
            rt = a.start_runtime(SimpleNamespace(), self._existing(
                {"id": "LFM2-1.2B-Q4_K_M.gguf", "label": "  "}))
        self.assertEqual((rt.lanes[0]["label"], rt.lanes[0]["maker"]),
                         ("LFM2 1.2B (baseline)", "Liquid AI"))

    def test_existing_server_sanitizes_non_ascii_and_long_labels(self):
        long_label = "Gemma 4 26B " + ("x" * 80)
        with patch.object(a, "say"):
            rt = a.start_runtime(SimpleNamespace(), self._existing(
                {"id": "raw\tid", "label": "Gemma 4 26B – instruct"}))
        self.assertEqual(rt.lanes[0]["lead_label"], "Gemma 4 26B instruct")
        self.assertTrue(proto.valid_model_label(rt.lanes[0]["lead_label"]))
        with patch.object(a, "say"):
            rt = a.start_runtime(SimpleNamespace(), self._existing({"id": long_label}))
        self.assertEqual(len(rt.lanes[0]["lead_label"]), 64)
        self.assertTrue(proto.valid_model_label(rt.lanes[0]["lead_label"]))
        self.assertTrue(rt.lanes[0]["lead_label"].startswith("Gemma 4 26B "))
        with patch.object(a, "say"):
            rt = a.start_runtime(SimpleNamespace(), self._existing(
                {"id": "LiquidAI/LFM2-VL-" + "x" * 80}))
        self.assertTrue(rt.lanes[0]["lead_label"].endswith(" (baseline)"))
        self.assertTrue(proto.valid_model_label(rt.lanes[0]["lead_label"]))
        self.assertEqual(rt.lanes[0]["maker"], "Liquid AI")

    def test_existing_server_rejects_a_missing_model_id(self):
        with patch.object(a, "say"), self.assertRaises(RuntimeError) as raised:
            a.start_runtime(SimpleNamespace(), self._existing({"id": None}))
        self.assertIn("usable model label", str(raised.exception))

    def test_served_model_label_skips_unusable_values(self):
        self.assertEqual(a.served_model_label("Gemma 4 26B – it", "fallback"), "Gemma 4 26B it")
        self.assertEqual(a.served_model_label(None, "\n\t"), None)
        self.assertEqual(a.served_model_label(None, 12, "ok"), "ok")
        self.assertTrue(proto.valid_model_label(a.served_model_label("é" * 8, "ASCII")))

    def test_managed_runtime_sets_lead_label_only_on_the_first_lane(self):
        args = a.arguments(["--own-server", "--no-download", "--port", "18090"])
        args.log_dir = Path("/unused/logs")
        args.models_dir = Path("/unused/models")
        args.runtime_dir = Path("/unused/runtime")
        args.companion_args = []
        info = {
            "gpu": {"name": "Apple M5 Pro", "vendor": "Apple", "backend": "cpu", "budget_mb": 8000},
            "runtime": {"type": "llama-server"},
            "model": {"choice": "local", "size_mb": 1000, "maker": "Google", "name": "lead.gguf"},
            "extras": [{"choice": "local", "size_mb": 400, "maker": "Qwen", "name": "extra.gguf"}],
        }
        server = type("Srv", (), {"base_url": "http://127.0.0.1:18090", "log_path": Path("/unused/server.log"),
                                  "stop": lambda self, quiet=False: None})()
        labels = iter(("Gemma 4 26B " + ("x" * 80), "Qwen extra"))
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(a, "ensure_llama_server", return_value=Path("/unused/llama-server")))
            stack.enter_context(patch.object(a, "runtime_env", return_value={}))
            stack.enter_context(patch.object(a, "probe_binary", return_value=(True, "fake")))
            stack.enter_context(patch.object(a, "ensure_model",
                                             side_effect=lambda *args, **kwargs: (Path("/unused/model"), next(labels))))
            stack.enter_context(patch.object(a, "launch_llama_server", return_value=server))
            stack.enter_context(patch.object(a, "wait_healthy", return_value=True))
            stack.enter_context(patch.object(a, "verify_gpu", return_value=(False, ["cpu"])))
            stack.enter_context(patch.object(a, "choose_port", side_effect=[18090, 18091]))
            stack.enter_context(patch.object(a, "new_key", return_value="k"))
            stack.enter_context(patch.object(a, "write_key_file", return_value=Path("/unused/k")))
            stack.enter_context(patch.object(a.Runtime, "start_guards"))
            stack.enter_context(patch.object(a.Runtime, "drop_key_file"))
            stack.enter_context(patch.object(a, "say"))
            rt = a.start_runtime(args, info)
        self.assertEqual(len(rt.lanes), 2)
        self.assertEqual(rt.lanes[0]["lead_label"], rt.lanes[0]["label"])
        self.assertEqual(len(rt.lanes[0]["lead_label"]), 64)
        self.assertTrue(proto.valid_model_label(rt.lanes[0]["lead_label"]))
        self.assertNotIn("lead_label", rt.lanes[1])
        with patch.object(a, "mac_model_name", return_value="MacBook Pro"):
            argv = a.companion_args(args, rt, info, Path("/unused/adb"), "SERIAL")
            self.assertEqual(argv[argv.index("--label") + 1], a.safe_label(info["gpu"]))
        self.assertEqual(a.safe_label(info["gpu"], "Darwin", "MacBook Pro"), "M5 Pro MacBook Pro")
        self.assertEqual(a.safe_label(info["gpu"], "Linux"), "M5 Pro PC")

    def test_managed_runtime_uses_file_name_when_selected_label_is_blank(self):
        args = a.arguments(["--own-server", "--no-download", "--port", "18090"])
        args.log_dir = Path("/unused/logs")
        args.models_dir = Path("/unused/models")
        args.runtime_dir = Path("/unused/runtime")
        info = {
            "gpu": {"name": "Apple M5 Pro", "vendor": "Apple", "backend": "cpu", "budget_mb": 8000},
            "runtime": {"type": "llama-server"},
            "model": {"choice": "local", "size_mb": 1000, "maker": "Local",
                      "name": "Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf"},
            "extras": [],
        }
        server = SimpleNamespace(base_url="http://127.0.0.1:18090",
                                 log_path=Path("/unused/server.log"))
        for selected_label in (None, ""):
            with self.subTest(selected_label=selected_label), contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(a, "ensure_llama_server", return_value=Path("/unused/server")))
                stack.enter_context(patch.object(a, "runtime_env", return_value={}))
                stack.enter_context(patch.object(a, "probe_binary", return_value=(True, "fake")))
                stack.enter_context(patch.object(a, "ensure_model",
                                                 return_value=(Path("/unused/model"), selected_label)))
                stack.enter_context(patch.object(a, "launch_llama_server", return_value=server))
                stack.enter_context(patch.object(a, "wait_healthy", return_value=True))
                stack.enter_context(patch.object(a, "verify_gpu", return_value=(False, ["cpu"])))
                stack.enter_context(patch.object(a, "choose_port", return_value=18090))
                stack.enter_context(patch.object(a, "new_key", return_value="fixture"))
                stack.enter_context(patch.object(a, "write_key_file", return_value=Path("/unused/key")))
                stack.enter_context(patch.object(a.Runtime, "start_guards"))
                stack.enter_context(patch.object(a.Runtime, "drop_key_file"))
                stack.enter_context(patch.object(a, "say"))
                rt = a.start_runtime(args, info)
            self.assertEqual((rt.lanes[0]["label"], rt.lanes[0]["maker"]),
                             ("Nemotron 3.5 Bolt", "NVIDIA"))


if __name__ == "__main__":
    unittest.main()

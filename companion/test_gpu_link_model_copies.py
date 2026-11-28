# SPDX-License-Identifier: Apache-2.0
"""Model-cache removal and GPU-memory checks without a display or live services."""

import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gpu_link_autosetup as setup
import opos_gpu_link as link


class FakeResponse(io.BytesIO):
    def __init__(self, content):
        super().__init__(content)
        self.headers = {"Content-Length": str(len(content))}


class FakeWidget:
    def __init__(self, **options):
        self.options = options

    def pack(self, **_options):
        pass


class FakeTk:
    def __init__(self):
        self.buttons = {}
        self.messages = []

    def StringVar(self, value):
        self.messages.append(value)
        return SimpleNamespace(set=self.messages.append)

    def Label(self, _root, **options):
        return FakeWidget(**options)

    def Button(self, _root, **options):
        self.buttons[options["text"]] = options["command"]
        return FakeWidget(**options)


class ModelCopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.models = self.data / "models"
        self.models.mkdir(parents=True)

    def download_copy(self, name="cached.gguf", content=b"companion copy"):
        entry = {"file": name, "repo": "fixture/model", "label": "Fixture",
                 "sha256": hashlib.sha256(content).hexdigest(), "size": len(content)}
        with patch.object(setup, "is_offline", return_value=False), \
                patch.object(setup.urllib.request, "urlopen", return_value=FakeResponse(content)), \
                patch.object(setup, "say"):
            path, _label = setup.ensure_model("download", entry, self.models)
        return path

    def test_removes_only_downloaded_cache_copies_and_sidecars(self):
        owned = self.download_copy()
        marker = setup._model_copy_marker(owned)
        verified = setup._sidecar(owned)
        self.assertTrue(marker.is_file())
        self.assertTrue(verified.is_file())
        manual = self.models / "manual.gguf"
        manual.write_bytes(b"placed by owner")
        outside = self.root / "lm-studio" / "models" / "outside.gguf"
        outside.parent.mkdir(parents=True)
        outside.write_bytes(b"external model")

        self.assertEqual(setup.remove_model_copies(self.data, self.models), 1)
        self.assertFalse(owned.exists())
        self.assertFalse(marker.exists())
        self.assertFalse(verified.exists())
        self.assertEqual(manual.read_bytes(), b"placed by owner")
        self.assertEqual(outside.read_bytes(), b"external model")

    def test_unmarked_existing_cache_file_is_left_alone(self):
        manual = self.models / "manual.gguf"
        manual.write_bytes(b"same bytes")
        entry = {"file": manual.name, "repo": "fixture/model", "label": "Fixture",
                 "sha256": hashlib.sha256(b"same bytes").hexdigest(), "size": 10}
        with patch.object(setup, "is_offline", return_value=False), \
                patch.object(setup.urllib.request, "urlopen") as fetch:
            setup.ensure_model("download", entry, self.models)
        fetch.assert_not_called()
        self.assertFalse(setup._model_copy_marker(manual).exists())
        self.assertEqual(setup.remove_model_copies(self.data, self.models), 0)
        self.assertTrue(manual.exists())

    def test_refuses_outside_or_symlinked_model_directory(self):
        outside = self.root / "other" / "models"
        outside.mkdir(parents=True)
        file = outside / "other.gguf"
        file.write_bytes(b"leave here")
        with self.assertRaises(ValueError):
            setup.remove_model_copies(self.data, outside)
        link_path = self.data / "models-link"
        try:
            link_path.symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Directory symlinks unavailable")
        with self.assertRaises(ValueError):
            setup.remove_model_copies(self.data, link_path)
        self.assertEqual(file.read_bytes(), b"leave here")

    def test_changed_marked_file_is_not_deleted(self):
        owned = self.download_copy()
        owned.write_bytes(b"changed by owner")
        self.assertEqual(setup.remove_model_copies(self.data, self.models), 0)
        self.assertEqual(owned.read_bytes(), b"changed by owner")

    def test_download_replaces_marker_symlink_without_touching_its_target(self):
        target = self.root / "outside.txt"
        target.write_text("leave here")
        marker = self.models / "cached.gguf.opos-copy"
        try:
            marker.symlink_to(target)
        except OSError:
            self.skipTest("File symlinks unavailable")
        owned = self.download_copy()
        self.assertFalse(marker.is_symlink())
        self.assertEqual(target.read_text(), "leave here")
        self.assertEqual(setup.remove_model_copies(self.data, self.models), 1)
        self.assertFalse(owned.exists())

    def test_window_button_confirms_and_logs_cache_removal(self):
        owned = self.download_copy()
        tk = FakeTk()
        root = SimpleNamespace(protocol=lambda *_args: None, configure=lambda **_kwargs: None)
        args = SimpleNamespace(adb="fake-adb", serial="PHONE", key_dir=self.data,
                               always_allow=False, data_dir=self.data, models_dir=self.models)
        with patch.object(link, "_dialog_fonts", return_value={"small": "S5", "body": "B5"}):
            app = link.Companion(args, root, tk)
        self.assertIn("Remove model copies", tk.buttons)
        with patch.object(link, "_confirm_remove_model_copies", return_value=False):
            tk.buttons["Remove model copies"]()
        self.assertTrue(owned.exists())
        with patch.object(link, "_confirm_remove_model_copies", return_value=True), \
                patch("builtins.print") as printed:
            tk.buttons["Remove model copies"]()
        self.assertFalse(owned.exists())
        self.assertIn(f"Removed model copies from {self.models} (1 file)", tk.messages[-1])
        printed.assert_called_once_with("GPU Link: " + tk.messages[-1], flush=True)

    def test_remove_keeps_fake_gpu_load_until_stop_then_samples_after(self):
        owned = self.download_copy()
        loaded = [True]
        events = []
        gpu = {"vendor": "NVIDIA", "backend": "cuda"}
        runtime = setup.Runtime()
        runtime.gpu = gpu
        runtime.memory_runner = lambda *_args, **_kwargs: self.fail("real GPU runner used")
        server = SimpleNamespace(port=18090, process=object(),
                                 stop=lambda: (events.append("stop"), loaded.__setitem__(0, False)))
        runtime.servers = [server]

        runners = []
        def used(_gpu, _runner=None):
            events.append("memory")
            runners.append(_runner)
            return 800 if loaded[0] else 100

        with patch.object(setup, "vram_used_mb", side_effect=used), patch.object(setup, "say") as log:
            self.assertEqual(setup.vram_used_mb(gpu), 800)
            self.assertEqual(setup.remove_model_copies(self.data, self.models), 1)
            self.assertFalse(owned.exists())
            self.assertEqual(setup.vram_used_mb(gpu), 800)
            runtime.stop()
            self.assertEqual(setup.vram_used_mb(gpu), 100)
        self.assertEqual(events, ["memory", "memory", "stop", "memory", "memory"])
        self.assertEqual(runners[2], runtime.memory_runner)
        log.assert_called_once_with("GPU use after stop: 100 MiB total.")

    def test_memory_probe_failure_does_not_block_fake_stop(self):
        for failure in (OSError("fixture probe failure"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                stopped = []
                runtime = setup.Runtime()
                runtime.gpu = {"vendor": "NVIDIA", "backend": "cuda"}
                runtime.servers = [SimpleNamespace(port=18090, process=object(),
                                                   stop=lambda: stopped.append(True))]
                with patch.object(setup, "vram_used_mb", side_effect=failure) as probe:
                    runtime.stop()
                self.assertEqual(stopped, [True])
                self.assertEqual(probe.call_count, 1)

    def test_partial_cleanup_failure_counts_the_deleted_model(self):
        owned = self.download_copy()
        marker = setup._model_copy_marker(owned)
        original = Path.unlink
        def unlink(path):
            if Path(path).resolve() == marker.resolve():
                raise OSError("fixture marker cleanup failure")
            return original(path)
        with patch.object(Path, "unlink", unlink):
            with self.assertRaises(RuntimeError) as error:
                setup.remove_model_copies(self.data, self.models)
        self.assertIn("Removed 1 model copy from", str(error.exception))
        self.assertIn("cleanup could not be completed", str(error.exception))
        self.assertFalse(owned.exists())
        self.assertTrue(marker.exists())

    def test_window_logs_when_the_cache_is_outside_the_data_directory(self):
        outside = self.root / "other" / "models"
        outside.mkdir(parents=True)
        tk = FakeTk()
        root = SimpleNamespace(protocol=lambda *_args: None, configure=lambda **_kwargs: None)
        args = SimpleNamespace(adb="fake-adb", serial="PHONE", key_dir=self.data,
                               always_allow=False, data_dir=self.data, models_dir=outside)
        with patch.object(link, "_dialog_fonts", return_value={"small": "S5", "body": "B5"}):
            app = link.Companion(args, root, tk)
        with patch.object(link, "_confirm_remove_model_copies") as confirm,                 patch("builtins.print") as printed:
            tk.buttons["Remove model copies"]()
        confirm.assert_not_called()
        message = "Model copies were not removed: the cache is not inside the companion data directory"
        self.assertEqual(tk.messages[-1], message)
        printed.assert_called_once_with("GPU Link: " + message, flush=True)

    def test_window_logs_a_partial_removal_error(self):
        owned = self.download_copy()
        tk = FakeTk()
        root = SimpleNamespace(protocol=lambda *_args: None, configure=lambda **_kwargs: None)
        args = SimpleNamespace(adb="fake-adb", serial="PHONE", key_dir=self.data,
                               always_allow=False, data_dir=self.data, models_dir=self.models)
        with patch.object(link, "_dialog_fonts", return_value={"small": "S5", "body": "B5"}):
            app = link.Companion(args, root, tk)
        failure = RuntimeError(f"Removed 1 model copy from {self.models}; cleanup could not be completed")
        with patch.object(link, "_confirm_remove_model_copies", return_value=True),                 patch.object(setup, "remove_model_copies", side_effect=failure),                 patch("builtins.print") as printed:
            tk.buttons["Remove model copies"]()
        self.assertTrue(owned.exists())
        self.assertEqual(tk.messages[-1], str(failure))
        printed.assert_called_once_with("GPU Link: " + str(failure), flush=True)


if __name__ == "__main__":
    unittest.main()

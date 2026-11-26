# SPDX-License-Identifier: Apache-2.0
"""choose_models scan roots and offline local-over-catalog fallback."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import gpu_link_autosetup as a


def _args(**kwargs):
    defaults = dict(models_dir=None, data_dir=None, model_path=None, budget_mb=None,
                    offline=False, no_download=False, no_extras=True, extras=0)
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _gpu(budget_mb=44000):
    return {"vendor": "Apple", "name": "Apple M5 Pro", "backend": "metal", "budget_mb": budget_mb}


class ScanRoots(unittest.TestCase):
    def test_models_dir_is_first_root_and_defaults_follow(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "home"
            data = Path(raw) / "data"
            extra = Path(raw) / "extra-models"
            for path in (home, data, extra):
                path.mkdir()
            with patch.object(a, "model_dirs", wraps=a.model_dirs) as wrapped:
                with patch.object(a.Path, "home", return_value=home):
                    # Avoid calling the real Path.home inside model_dirs by passing through wraps
                    # and stubbing Path.home used by model_dirs.
                    roots = a.scan_roots(_args(models_dir=extra, data_dir=data))
            self.assertEqual(roots[0], extra)
            # model_dirs was asked for the data dir (LM Studio and default folders come from there).
            wrapped.assert_called_once_with(here=data)

    def test_models_dir_and_lmstudio_and_default_folders_are_scan_roots(self):
        with tempfile.TemporaryDirectory() as raw:
            home = Path(raw) / "home"
            data = Path(raw) / "data"
            extra = Path(raw) / "extra-models"
            for path in (home, data, extra):
                path.mkdir()
            with patch.object(Path, "home", return_value=home):
                roots = a.scan_roots(_args(models_dir=extra, data_dir=data))
            rendered = [Path(root) for root in roots]
            self.assertEqual(rendered[0], extra)
            self.assertIn(data / "models", rendered)
            self.assertIn(home / ".lmstudio" / "models", rendered)
            self.assertIn(home / ".cache" / "lm-studio" / "models", rendered)
            self.assertIn(home / ".cache" / "llama.cpp", rendered)
            self.assertIn(home / "models", rendered)
            self.assertIn(home / "Models", rendered)

    def test_existing_model_path_parent_is_a_scan_root(self):
        with tempfile.TemporaryDirectory() as raw:
            folder = Path(raw) / "elsewhere"
            folder.mkdir()
            gguf = folder / "Qwen3-4B-Q4_K_M.gguf"
            gguf.write_bytes(b"x")
            data = Path(raw) / "data"
            data.mkdir()
            with patch.object(Path, "home", return_value=Path(raw) / "home"):
                roots = a.scan_roots(_args(data_dir=data, model_path=str(gguf)))
            self.assertIn(folder.resolve(), [Path(root).resolve() for root in roots])

    def test_duplicate_models_dir_and_data_models_are_deduped(self):
        with tempfile.TemporaryDirectory() as raw:
            data = Path(raw) / "data"
            models = data / "models"
            models.mkdir(parents=True)
            with patch.object(Path, "home", return_value=Path(raw) / "home"):
                roots = a.scan_roots(_args(models_dir=models, data_dir=data))
            resolved = [Path(root).resolve() for root in roots]
            self.assertEqual(resolved.count(models.resolve()), 1)


class ChooseModelsOffline(unittest.TestCase):
    def test_offline_uses_models_dir_file_instead_of_catalog_download(self):
        # Huge budget would normally prefer downloading Gemma 3 12B over a 1.7 GB local file.
        local = [{"path": "/extra/LFM3-1.7B-Q8_0.gguf", "name": "LFM3-1.7B-Q8_0.gguf",
                  "size_mb": 1760, "label": "LFM3-1.7B", "maker": "Liquid AI"}]
        args = _args(models_dir=Path("/extra"), data_dir=Path("/data"), offline=True)
        with patch.object(a, "scan_roots", return_value=[Path("/extra"), Path("/data/models")]) as roots, \
                patch.object(a, "scan_local_ggufs", return_value=local) as scan:
            model, extras = a.choose_models(args, _gpu(44000), None)
        roots.assert_called_once_with(args)
        scan.assert_called_once_with(roots.return_value)
        self.assertEqual(model["choice"], "local")
        self.assertEqual(model["name"], "LFM3-1.7B-Q8_0.gguf")
        self.assertEqual(model["local_found"], 1)

    def test_no_download_alone_still_prefers_much_bigger_catalog(self):
        # --no-download refuses the fetch later; only --offline changes the pick.
        local = [{"path": "/extra/Qwen3-4B-Q4_K_M.gguf", "name": "Qwen3-4B-Q4_K_M.gguf",
                  "size_mb": 2381, "label": "Qwen3-4B", "maker": "Qwen"}]
        args = _args(models_dir=Path("/extra"), data_dir=Path("/data"), no_download=True)
        with patch.object(a, "scan_roots", return_value=[Path("/extra")]), \
                patch.object(a, "scan_local_ggufs", return_value=local):
            model, _ = a.choose_models(args, _gpu(44000), None)
        self.assertEqual(model["choice"], "download")
        self.assertTrue(str(model.get("file") or model.get("name")).startswith("gemma-3-12b"))

    def test_online_still_prefers_much_bigger_catalog(self):
        local = [{"path": "/extra/tiny.gguf", "name": "tiny.gguf",
                  "size_mb": 470, "label": "tiny", "maker": "Local"}]
        args = _args(models_dir=Path("/extra"), data_dir=Path("/data"), offline=False)
        with patch.object(a, "scan_roots", return_value=[Path("/extra")]), \
                patch.object(a, "scan_local_ggufs", return_value=local):
            model, _ = a.choose_models(args, _gpu(12000), None)
        self.assertEqual(model["choice"], "download")
        self.assertTrue(str(model.get("file") or model.get("name")).startswith("gemma-3-12b"))

    def test_offline_with_no_local_still_reports_download_choice(self):
        # Honest: there is nothing local to use; start_runtime will still refuse the download.
        args = _args(data_dir=Path("/data"), offline=True)
        with patch.object(a, "scan_roots", return_value=[Path("/data/models")]), \
                patch.object(a, "scan_local_ggufs", return_value=[]):
            model, _ = a.choose_models(args, _gpu(12000), None)
        self.assertEqual(model["choice"], "download")
        self.assertEqual(model["local_found"], 0)

    def test_prefer_model_path_among_scanned_locals_when_offline(self):
        local = [
            {"path": "/extra/LFM3-1.7B-Q8_0.gguf", "name": "LFM3-1.7B-Q8_0.gguf",
             "size_mb": 1760, "label": "LFM3-1.7B", "maker": "Liquid AI"},
            {"path": "/extra/Qwen3-4B-Q4_K_M.gguf", "name": "Qwen3-4B-Q4_K_M.gguf",
             "size_mb": 2381, "label": "Qwen3-4B", "maker": "Qwen"},
        ]
        args = _args(models_dir=Path("/extra"), data_dir=Path("/data"),
                     model_path="Qwen3-4B-Q4_K_M.gguf", offline=True)
        with patch.object(a, "scan_roots", return_value=[Path("/extra")]), \
                patch.object(a, "scan_local_ggufs", return_value=local):
            model, _ = a.choose_models(args, _gpu(44000), None)
        self.assertEqual((model["choice"], model["name"]), ("local", "Qwen3-4B-Q4_K_M.gguf"))


if __name__ == "__main__":
    unittest.main()

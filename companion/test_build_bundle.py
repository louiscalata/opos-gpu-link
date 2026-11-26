# SPDX-License-Identifier: Apache-2.0
"""build_bundle.py stages adb only when asked; no network, no PyInstaller run."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import build_bundle as b


class NoAdbTests(unittest.TestCase):
    def build(self, *argv):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "companion").mkdir()
            calls = {"pyinstaller": None}

            def fake_run(cmd, check=True, **kwargs):
                calls["pyinstaller"] = cmd
                out = Path(cmd[cmd.index("--distpath") + 1])
                out.mkdir(parents=True, exist_ok=True)
                (out / "opos-gpu-link").write_bytes(b"x")
                return mock.Mock(returncode=0)

            with mock.patch.object(b, "HERE", root / "companion"), \
                    mock.patch.object(b.platform, "system", return_value="Linux"), \
                    mock.patch.object(b.platform, "machine", return_value="x86_64"), \
                    mock.patch.object(b.a, "official_bundle_llama_archives", return_value=[]), \
                    mock.patch.object(b.a, "download") as download, \
                    mock.patch.object(b.a, "extract") as extract, \
                    mock.patch.object(b, "stage_adb") as stage_adb, \
                    mock.patch.object(b.subprocess, "run", side_effect=fake_run):
                b.main(["--out", str(root / "bundles"), *argv])
                stage = root / "build-work" / "Linux-x86_64" / "bundled"
                return stage_adb, download, extract, calls, stage.is_dir()

    def test_no_adb_skips_platform_tools(self):
        stage_adb, download, extract, calls, staged = self.build("--no-adb")
        stage_adb.assert_not_called()
        download.assert_not_called()
        extract.assert_not_called()
        self.assertTrue(staged)
        self.assertIn("--add-data", calls["pyinstaller"])

    def test_default_still_stages_adb(self):
        stage_adb, _, _, _, _ = self.build()
        stage_adb.assert_called_once()
        self.assertEqual(stage_adb.call_args.args[0], "Linux")


if __name__ == "__main__":
    unittest.main()

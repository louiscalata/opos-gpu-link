# SPDX-License-Identifier: Apache-2.0
"""A Mac is never called a PC on the companion's screens. No adb, no phone, no network."""
import ast
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gpu_link_autosetup as setup  # noqa: E402
import opos_gpu_link as link  # noqa: E402

# Pairing labels on the wire stay as they are: the phone's saved pairing is bound to them.
# "PC" alone is computer_noun's answer for a Windows or Linux computer.
ALLOWED = {"OPOS GPU PC", "GPU PC", " PC", "Stand-in PC", "PC"}


class ComputerNounTest(unittest.TestCase):
    def test_mac_laptop_with_battery_is_a_macbook(self):
        self.assertEqual(link.computer_noun("Darwin", "Mac17,9", True), "MacBook")

    def test_mac_desktop_without_battery_is_a_mac(self):
        self.assertEqual(link.computer_noun("Darwin", "Mac16,10", False), "Mac")

    def test_intel_macbook_model_id_is_a_macbook_without_asking_for_power(self):
        with patch.object(link, "_quiet_output", side_effect=AssertionError("no query")):
            self.assertEqual(link.computer_noun("Darwin", "MacBookPro18,1"), "MacBook")

    def test_windows_and_linux_stay_pc(self):
        for system in ("Windows", "Linux"):
            self.assertEqual(link.computer_noun(system, "", True), "PC")

    def test_failed_queries_on_a_mac_still_say_mac(self):
        def broken(*_args, **_kwargs):
            raise OSError("missing")
        with patch.object(link.subprocess, "run", side_effect=broken):
            self.assertEqual(link.computer_noun("Darwin"), "Mac")

    def test_reads_model_id_and_battery_from_local_tools(self):
        replies = {link.MAC_MODEL_ID: "Mac17,9\n", link.MAC_POWER: "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t92%\n"}

        def run(argv, **_kwargs):
            return SimpleNamespace(returncode=0, stdout=replies[argv[0]])
        with patch.object(link.subprocess, "run", side_effect=run):
            self.assertEqual(link.computer_noun("Darwin"), "MacBook")

    def test_default_answer_is_cached(self):
        calls = []

        def once(system=None):
            calls.append(1)
            return "Linux"
        with patch.object(link, "_NOUN_CACHE", []), patch.object(link.platform, "system", side_effect=once):
            self.assertEqual(link.computer_noun(), "PC")
            self.assertEqual(link.computer_noun(), "PC")
        self.assertEqual(len(calls), 1)


class ScreenWordsTest(unittest.TestCase):
    def test_ready_banner_names_the_mac(self):
        lanes = [{"label": "Nemotron 3.5 Bolt E4B"}, {"label": "Small"}]
        lines = setup.ready_lines("Apple M5 Pro", lanes, "MacBook")
        self.assertIn("MacBook answer lanes: 2 (Nemotron 3.5 Bolt E4B, Small)", lines)
        self.assertIn("First time only: compare the 6-digit code and tap Allow on the phone.", lines)
        self.assertFalse([line for line in lines if "PC" in line.split()])

    def test_ready_banner_on_a_pc_still_says_pc(self):
        self.assertIn("PC answer lanes: 0 ()", setup.ready_lines("RTX 5080", [], "PC"))

    def test_grant_messages_use_the_noun(self):
        app = SimpleNamespace(granted=False, headless=True)
        with patch.object(link, "computer_noun", return_value="MacBook"):
            with self.assertRaisesRegex(link.GrantDeclined, r"^MacBook grant expired"):
                link.Companion.ensure_permission(app)

    def test_no_screen_string_calls_the_computer_a_pc(self):
        """Every string literal in the companion's screen code, apart from wire labels."""
        found = []
        for name in ("opos_gpu_link.py", "gpu_link_autosetup.py"):
            tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
            docs = {id(node.body[0].value) for node in ast.walk(tree)
                    if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                    and node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)}
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs
                        and node.value not in ALLOWED
                        and any(word.strip(".,;:!?'\"()") == "PC" for word in node.value.split())):
                    found.append(f"{name}:{node.lineno}: {node.value[:60]}")
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()

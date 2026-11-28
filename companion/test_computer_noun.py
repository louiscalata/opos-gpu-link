# SPDX-License-Identifier: Apache-2.0
"""A Mac is never called a PC on the companion's screens. No adb, no phone, no network."""
import ast
import re
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gpu_link_autosetup as setup  # noqa: E402
import opos_gpu_link as link  # noqa: E402

# Wire labels for Windows or Linux computers keep "PC"; "PC" alone is computer_noun's answer there.
ALLOWED = {"Stand-in PC", "PC"}
# safe_label builds "<GPU> PC" for non-Macs; only these two literals there are exempt.
WIRE_LABEL_FUNCTION = "safe_label"
WIRE_LABEL_PARTS = {" PC", "GPU PC"}
SCANNED = ("opos_gpu_link.py", "gpu_link_autosetup.py", "gpu_link_worker.py")
PC_WORD = re.compile(r"\bPCs?\b")


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

    def test_desktop_mac_on_a_ups_is_a_mac(self):
        ups = "Now drawing from 'UPS Power'\n -CP1500PFCLCD (id=3)\t100%; charged\n"
        replies = {link.MAC_MODEL_ID: "Mac16,10\n", link.MAC_POWER: ups}

        def run(argv, **_kwargs):
            return SimpleNamespace(returncode=0, stdout=replies[argv[0]])
        with patch.object(link.subprocess, "run", side_effect=run):
            self.assertEqual(link.computer_noun("Darwin"), "Mac")

    def test_timeouts_and_failed_exits_read_as_no_answer(self):
        def slow(argv, **kwargs):
            self.assertIs(kwargs.get("stdin"), subprocess.DEVNULL)
            self.assertLessEqual(kwargs.get("timeout"), 2)
            raise subprocess.TimeoutExpired(argv, kwargs.get("timeout"))
        with patch.object(link.subprocess, "run", side_effect=slow):
            self.assertEqual(link._quiet_output(["/usr/sbin/sysctl"]), "")
            self.assertEqual(link.computer_noun("Darwin"), "Mac")
        failed = SimpleNamespace(returncode=1, stdout="InternalBattery")
        with patch.object(link.subprocess, "run", return_value=failed):
            self.assertEqual(link.computer_noun("Darwin"), "Mac")

    def test_main_warms_the_noun_before_the_link_starts(self):
        seen = []

        def stop_at_adb(adb):
            seen.append("adb")
            raise link.CompanionError("stop here")
        # An explicit --server turns auto-discovery off; never probe a real local backend here.
        with patch.object(link, "computer_noun", side_effect=lambda: seen.append("noun") or "Mac"), \
                patch.object(link.gpu_link_discover, "_probe", side_effect=AssertionError("no probe")), \
                patch.object(link, "resolve_launch_adb", side_effect=stop_at_adb):
            self.assertEqual(link.main(["--model", "m", "--server", "http://127.0.0.1:9/v1/chat/completions"]), 2)
        self.assertEqual(seen, ["noun", "noun", "adb"])

    def test_discover_only_does_not_query_the_computer(self):
        with patch.object(link, "computer_noun", side_effect=AssertionError("no query")), \
                patch.object(link.gpu_link_discover, "_probe", side_effect=AssertionError("no probe")), \
                patch.object(link.gpu_link_discover, "print_discovery", return_value=None):
            self.assertEqual(link.main(["--discover"]), 0)

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
        lanes = [{"label": "Nemotron 3.5 Bolt"}, {"label": "LFM2 1.2B (baseline)"}]
        lines = setup.ready_lines("Apple M5 Pro", lanes, "MacBook")
        self.assertIn("MacBook GPU: Apple M5 Pro.", lines)
        self.assertIn("Models ready: Nemotron 3.5 Bolt, LFM2 1.2B (baseline).", lines)
        self.assertIn("Wireless: coming later.", lines)
        self.assertFalse([line for line in lines if "PC" in line.split()])

    def test_ready_banner_on_a_pc_still_says_pc(self):
        self.assertIn("PC GPU: RTX 5080.", setup.ready_lines("RTX 5080", [], "PC"))

    def test_wire_label_names_a_mac_as_a_mac(self):
        self.assertEqual(setup.safe_label({"name": "Apple M5 Pro"}, "Darwin", "MacBook Pro"), "M5 Pro MacBook Pro")
        self.assertEqual(setup.safe_label({"name": "NVIDIA GeForce RTX 5080"}, "Linux"), "RTX 5080 PC")
        self.assertEqual(setup.safe_label({}, "Windows"), "GPU PC")

    def test_direct_companion_label_uses_the_computer_noun(self):
        with patch.object(link, "computer_noun", return_value="MacBook"):
            args = link.arguments(["--serial", "PHONE", "--model", "local",
                                   "--server", "http://127.0.0.1:9/v1/chat/completions"])
        self.assertEqual(args.label, "OPOS GPU MacBook")

    def test_grant_messages_use_the_noun(self):
        app = SimpleNamespace(granted=False, headless=True)
        with patch.object(link, "computer_noun", return_value="MacBook"):
            with self.assertRaisesRegex(link.GrantDeclined, r"^Error: MacBook access expired"):
                link.Companion.ensure_permission(app)
            app = SimpleNamespace(granted=False, headless=False, permission=lambda: False)
            with self.assertRaisesRegex(link.GrantDeclined, r"^Error: MacBook access was declined"):
                link.Companion.ensure_permission(app)

    def test_no_screen_string_calls_the_computer_a_pc(self):
        """String literals and f-string parts in the companion, worker and launcher, including
        module docstrings (shown by --help); only function and class docstrings are skipped."""
        found = []
        for name in SCANNED:
            tree = ast.parse((HERE / name).read_text(encoding="utf-8"))
            skipped = set()
            for node in ast.walk(tree):
                if (isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and node.body
                        and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)):
                    skipped.add(id(node.body[0].value))
                if isinstance(node, ast.FunctionDef) and node.name == WIRE_LABEL_FUNCTION:
                    skipped.update(id(inner) for inner in ast.walk(node)
                                   if isinstance(inner, ast.Constant) and inner.value in WIRE_LABEL_PARTS)
            for node in ast.walk(tree):
                if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skipped
                        and node.value not in ALLOWED and PC_WORD.search(node.value)):
                    found.append(f"{name}:{node.lineno}: {node.value[:60]}")
        self.assertEqual(found, [])

    def test_scanner_catches_possessives_and_compounds(self):
        for text in ("this PC's GPU", "PC-side", "PC/phone", "a PC.", "two PCs"):
            self.assertTrue(PC_WORD.search(text), text)


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""Device-free checks for the read-only demo checklist."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("show_preflight", Path(__file__).with_name("show_preflight.py"))
assert SPEC is not None and SPEC.loader is not None
preflight = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preflight)


SERIAL = "demo-123"
LISTING = f"List of devices attached\n{SERIAL} device product:demo model:Flip\n"
READS = {
    ("devices", "-l"): LISTING,
    ("-s", SERIAL, "shell", "dumpsys", "thermalservice"): "Thermal Status: 2\n",
    ("-s", SERIAL, "shell", "dumpsys", "battery"): "  USB powered: true\n  level: 72\n",
    ("-s", SERIAL, "shell", "dumpsys", "SurfaceFlinger", "--display-id"):
        "Display 4619827551948147201 (HWC display 0)\nDisplay 9 (HWC display 1)\n",
    ("-s", SERIAL, "shell", "dumpsys", "window"):
        "mScreenOnFully=true mShowingLockscreen=false\n",
}


class FakeRunner:
    def __init__(self, replacements=None):
        self.responses = {**READS, **(replacements or {})}
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(tuple(argv))
        if kwargs != {"capture_output": True, "text": True, "check": False, "timeout": 10}:
            raise AssertionError(f"unexpected runner options: {kwargs}")
        response = self.responses[tuple(argv[1:])]
        if isinstance(response, Exception):
            raise response
        if isinstance(response, tuple):
            code, output = response
        else:
            code, output = 0, response
        return subprocess.CompletedProcess(argv, code, output, "")


class ShowPreflightTests(unittest.TestCase):
    def run_check(self, replacements=None, args=None):
        fake = FakeRunner(replacements)
        lines = []
        # All tests inject FakeRunner; a fallback to the real subprocess is an error.
        with patch.object(preflight.subprocess, "run", side_effect=AssertionError("real adb called")):
            code = preflight.main(args or [], runner=fake, emit=lines.append)
        return code, lines, fake.calls

    def test_good_check_and_every_argv_is_allowlisted(self):
        code, lines, calls = self.run_check(args=["--adb", "/fake/adb"])
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(preflight.allowed_argv(call, "/fake/adb", SERIAL) for call in calls))
        self.assertEqual([line.split()[0] for line in lines], ["PASS"] * 5)
        self.assertIn("USB powered yes", lines[2])
        self.assertIn("4619827551948147201, 9", lines[3])
        self.assertIn("keyguard unlocked", lines[4])
        for forbidden in (("start-server",), ("kill-server",), ("reconnect",),
                          ("-s", SERIAL, "shell", "input", "keyevent", "1"),
                          ("-s", SERIAL, "shell", "dumpsys", "power", "--set")):
            self.assertFalse(preflight.allowed_argv(("/fake/adb", *forbidden), "/fake/adb", SERIAL))
        fake = FakeRunner()
        with self.assertRaises(ValueError):
            preflight.read_adb(["adb", "start-server"], "adb", SERIAL, fake)
        self.assertEqual(fake.calls, [])

    def test_device_selection_requires_one_authorized_device_or_serial(self):
        second = "other-456 device model:Other\n"
        for listing in ("List of devices attached\n",
                        f"List of devices attached\n{SERIAL} unauthorized\n",
                        f"List of devices attached\n{SERIAL} offline\n",
                        LISTING + second):
            with self.subTest(listing=listing):
                code, lines, calls = self.run_check({("devices", "-l"): listing})
                self.assertEqual(code, 1)
                self.assertTrue(lines[0].startswith("FAIL device:"))
                self.assertTrue(lines[1].startswith("Fix:"))
                self.assertEqual(calls, [("adb", "devices", "-l")])

        code, lines, calls = self.run_check(
            {("devices", "-l"): LISTING + second}, ["--serial", SERIAL])
        self.assertEqual(code, 0)
        self.assertEqual(len(calls), 5)
        self.assertTrue(all(preflight.allowed_argv(call, "adb", SERIAL) for call in calls))
        self.assertEqual(lines[0], f"PASS device: {SERIAL}")

        code, lines, calls = self.run_check(args=["--serial", "absent"])
        self.assertEqual(code, 1)
        self.assertEqual(len(calls), 1)
        self.assertTrue(lines[0].startswith("FAIL device:"))

    def test_thermal_thresholds_and_read_failure(self):
        key = ("-s", SERIAL, "shell", "dumpsys", "thermalservice")
        for status, grade, code in ((0, "PASS", 0), (2, "PASS", 0),
                                    (3, "WARN", 0), (4, "FAIL", 1), (5, "FAIL", 1)):
            with self.subTest(status=status):
                actual, lines, _ = self.run_check({key: f"Thermal Status: {status}\n"})
                self.assertEqual(actual, code)
                self.assertEqual(lines[1], f"{grade} thermal: status {status}")
        code, lines, _ = self.run_check({key: (1, "")})
        self.assertEqual(code, 1)
        self.assertEqual(lines[1], "FAIL thermal: read unavailable")

    def test_low_battery_missing_display_and_locked_screen_warn(self):
        replacements = {
            ("-s", SERIAL, "shell", "dumpsys", "battery"):
                "level: 29\nUSB powered: false\n",
            ("-s", SERIAL, "shell", "dumpsys", "SurfaceFlinger", "--display-id"):
                "No displays\n",
            ("-s", SERIAL, "shell", "dumpsys", "window"):
                "mScreenOn=true mKeyguardLocked=true\n",
        }
        code, lines, _ = self.run_check(replacements)
        self.assertEqual(code, 0)
        self.assertEqual(lines[2], "WARN battery: 29%; USB powered no")
        self.assertEqual(lines[3], "WARN display IDs: none found")
        self.assertEqual(lines[4], "WARN screen: on; keyguard locked")

    def test_unavailable_device_listing_fails_without_other_commands(self):
        code, lines, calls = self.run_check({("devices", "-l"): (1, "")})
        self.assertEqual(code, 1)
        self.assertEqual(calls, [("adb", "devices", "-l")])
        self.assertEqual(lines[0], "FAIL device: adb devices unavailable")
        self.assertTrue(lines[1].startswith("Fix:"))


if __name__ == "__main__":
    unittest.main()

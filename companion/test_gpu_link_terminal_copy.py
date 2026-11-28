# SPDX-License-Identifier: Apache-2.0
"""Presenter lines without a phone, model server, or network request."""

import contextlib
import io
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import gpu_link_autosetup as setup
import opos_gpu_link as link


class TerminalCopyTests(unittest.TestCase):
    def test_waiting_phone_states_use_one_actionable_line_each(self):
        for state, message in setup.PHONE_TEXT.items():
            with self.subTest(state=state):
                output = io.StringIO()
                with contextlib.redirect_stdout(output), \
                        patch.object(setup, "phone_state", return_value=(state, None)), \
                        patch.object(setup, "_run", return_value=""):
                    result = setup.wait_for_phone("unused", sleep=lambda _: None, timeout=-1)
                self.assertIsNone(result)
                self.assertEqual(output.getvalue().splitlines(), ["GPU Link: " + message])
                if state != "none":
                    self.assertTrue(message.startswith("Error: "))

    def test_status_deduplicates_and_keeps_expected_errors_on_one_line(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            status = link.ConsoleStatus()
            status.set("Answer started.")
            status.set("Answer started.")
            status.set("Error: Model port is busy. Free it, then retry.")
        self.assertEqual(output.getvalue().splitlines(), [
            "GPU Link: Answer started.",
            "GPU Link: Error: Model port is busy. Free it, then retry.",
        ])

    def test_busy_model_port_is_reported_without_traceback(self):
        output = io.StringIO()
        args = SimpleNamespace(detect_only=False, prefetch=False, no_phone=False)
        info = {"gpu": {"note": ""}}
        with contextlib.redirect_stdout(output), \
                patch.object(setup, "install_term_handler"), \
                patch.object(setup, "plan", return_value=info), \
                patch.object(setup, "start_runtime", side_effect=RuntimeError("No free port in 38400-38409")):
            self.assertEqual(setup.run(args), 2)
        self.assertEqual(output.getvalue().splitlines(), [
            "GPU Link: Error: Model ports are busy. Stop a model server using them, then retry."
        ])

    def test_companion_expected_failures_have_a_next_action(self):
        for reason in ("More than one authorized USB phone is present; pass --serial",
                       "GPU Link is already running for this phone, or its lock is unavailable",
                       "adb is unavailable"):
            line = link.presenter_error(link.CompanionError(reason))
            self.assertTrue(line.startswith("Error: "))
            self.assertIn(".", line)
            self.assertTrue(any(action in line for action in ("Unplug", "Stop", "Install")))

    def test_pairing_file_errors_do_not_print_a_path_or_blame_the_phone(self):
        for reason in (PermissionError(13, "Permission denied", "/private/pairing/lock"),
                       OSError(2, "Missing", "/private/other/lock")):
            with self.subTest(reason=type(reason).__name__):
                line = link.presenter_error(reason)
                self.assertEqual(line, "Error: Pairing folder is unavailable. Check file access on this computer, then retry.")
                self.assertNotIn("/private", line)

    def test_companion_error_fallback_handles_empty_and_other_phone_mentions(self):
        self.assertEqual(link.presenter_error(link.CompanionError("")),
                         "Error: GPU Link stopped. Restart it, then retry.")
        self.assertEqual(link.presenter_error(link.CompanionError("Phone model setting invalid")),
                         "Error: Phone model setting invalid. Check setup, then retry.")

    def test_setup_error_names_the_step_without_printing_a_path(self):
        for stage, error, expected in (
            ("plan", OSError(13, "Permission denied", "/private/setup"),
             "Error: Could not check this computer. Check its settings, then retry."),
            ("model", RuntimeError("GPU failed at /private/model"),
             "Error: Model setup stopped. Check the model server log, then retry."),
            ("usb", OSError(2, "Missing", "/private/usb"),
             "Error: USB setup stopped. Check the cable and USB tools, then retry."),
            ("phone", ValueError("Unexpected state at /private/phone"),
             "Error: Phone connection stopped. Check the cable and USB access, then retry."),
            ("link", RuntimeError("Unknown link failure at /private/link"),
             "Error: GPU Link stopped. Check the phone and model server, then retry."),
        ):
            with self.subTest(stage=stage):
                line = setup.setup_error_message(error, stage)
                self.assertEqual(line, expected)
                self.assertNotIn("/private", line)

    def test_run_catches_plan_file_error_without_a_traceback(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), \
                patch.object(setup, "install_term_handler"), \
                patch.object(setup, "plan", side_effect=OSError(13, "Denied", "/private/setup")):
            self.assertEqual(setup.run(SimpleNamespace()), 2)
        self.assertEqual(output.getvalue().splitlines(), [
            "GPU Link: Error: Could not check this computer. Check its settings, then retry."])

    def test_run_catches_usb_file_error_and_stops_owned_runtime(self):
        output = io.StringIO()
        runtime = SimpleNamespace(stop=Mock())
        args = SimpleNamespace(detect_only=False, prefetch=False, no_phone=False,
                               runtime_dir=Path("unused"), adb=None, no_download=True,
                               keep_server=False)
        with contextlib.redirect_stdout(output), \
                patch.object(setup, "install_term_handler"), \
                patch.object(setup, "plan", return_value={"gpu": {"note": ""}}), \
                patch.object(setup, "start_runtime", return_value=runtime), \
                patch.object(setup, "ensure_adb", side_effect=OSError(2, "Missing", "/private/usb")):
            self.assertEqual(setup.run(args), 2)
        runtime.stop.assert_called_once_with()
        self.assertEqual(output.getvalue().splitlines(), [
            "GPU Link: Error: USB setup stopped. Check the cable and USB tools, then retry."])

    def test_main_hides_guard_file_error(self):
        output = io.StringIO()
        with contextlib.redirect_stderr(output), \
                patch.object(link, "InstanceGuard", side_effect=PermissionError(13, "Denied", "/private/pairing/lock")):
            self.assertEqual(link.main(["--reset-pairing", "--serial", "PHONE",
                                        "--server", "http://127.0.0.1:9/v1/chat/completions"]), 2)
        self.assertEqual(output.getvalue().splitlines(), [
            "GPU Link: Error: Pairing folder is unavailable. Check file access on this computer, then retry."])


if __name__ == "__main__":
    unittest.main()

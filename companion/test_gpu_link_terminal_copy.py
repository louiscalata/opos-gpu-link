# SPDX-License-Identifier: Apache-2.0
"""Presenter lines without a phone, model server, or network request."""

import contextlib
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
            "GPU Link: Error: Model ports are busy. Stop a model server using them or choose another --port."
        ])

    def test_companion_expected_failures_have_a_next_action(self):
        for reason in ("More than one authorized USB phone is present; pass --serial",
                       "GPU Link is already running for this phone, or its lock is unavailable",
                       "adb is unavailable"):
            line = link.presenter_error(link.CompanionError(reason))
            self.assertTrue(line.startswith("Error: "))
            self.assertIn(".", line)
            self.assertTrue(any(action in line for action in ("Unplug", "Stop", "Install")))


if __name__ == "__main__":
    unittest.main()

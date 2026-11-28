# SPDX-License-Identifier: Apache-2.0
"""Main-window layout checks without opening a display or contacting a phone."""

import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import opos_gpu_link as link


class FakeVar:
    def __init__(self, value):
        self.value = value
        self.traces = []

    def get(self):
        return self.value

    def set(self, value):
        self.value = value
        for callback in self.traces:
            callback("", "", "write")

    def trace_add(self, mode, callback):
        assert mode == "write"
        self.traces.append(callback)


class FakeWidget:
    def __init__(self, parent=None, **options):
        self.parent = parent
        self.options = options
        self.children = []
        self.grid_options = None
        self.column_weights = {}
        self.column_options = {}
        self.row_weights = {}
        self.bindings = {}
        if parent is not None:
            parent.children.append(self)

    def configure(self, **options):
        self.options.update(options)

    def grid(self, **options):
        self.grid_options = options

    def columnconfigure(self, column, *, weight, **options):
        self.column_weights[column] = weight
        self.column_options[column] = options

    def rowconfigure(self, row, *, weight):
        self.row_weights[row] = weight

    def minsize(self, width, height):
        self.minimum = (width, height)

    def bind(self, event, callback):
        self.bindings[event] = callback

    def protocol(self, name, callback):
        self.protocols = {name: callback}


class FakeRoot(FakeWidget):
    def __init__(self):
        super().__init__()
        self.scheduled = []
        self.destroyed = False

    def after(self, delay, callback):
        self.scheduled.append((delay, callback))

    def destroy(self):
        self.destroyed = True

    def mainloop(self):
        return None


class FakeTk:
    def __init__(self):
        self.labels = []
        self.buttons = []

    def Frame(self, parent, **options):
        return FakeWidget(parent, **options)

    def Label(self, parent, **options):
        label = FakeWidget(parent, **options)
        self.labels.append(label)
        return label

    def Button(self, parent, **options):
        button = FakeWidget(parent, **options)
        self.buttons.append(button)
        return button

    def StringVar(self, *, value):
        return FakeVar(value)


class MainWindowTests(unittest.TestCase):
    def window_app(self):
        root, tk = FakeRoot(), FakeTk()
        args = SimpleNamespace(adb="unused", serial="fixture", key_dir=Path("unused"),
                               always_allow=False, server="http://127.0.0.1:18090/v1/chat/completions")
        with patch.object(link, "_dialog_fonts", return_value={
                "title": "H5", "small": "S5", "body": "B5"}), \
                patch.object(link, "computer_noun", return_value="MacBook"):
            app = link.Companion(args, root, tk)
        return app, root, tk

    def test_phone_is_left_computer_is_right_and_status_grows(self):
        root, tk = FakeWidget(), FakeTk()
        status = FakeVar("Waiting for the phone on USB.")
        window = link._build_main_window(
            tk, root, status, "MacBook", {"title": "H5", "small": "S5", "body": "B5"},
            lambda: None, lambda: None, lambda: None,
        )
        phone, computer = window["phone_panel"], window["computer_panel"]
        band = phone.parent
        self.assertIs(computer.parent, band)
        self.assertEqual(phone.grid_options["column"], 0)
        self.assertEqual(window["link_label"].grid_options["column"], 1)
        self.assertEqual(computer.grid_options["column"], 2)
        self.assertEqual((band.column_weights[0], band.column_weights[2]), (1, 1))
        self.assertEqual((band.column_options[0], band.column_options[2]),
                         ({"uniform": "device"}, {"uniform": "device"}))
        self.assertEqual(root.minimum, (600, 300))
        self.assertEqual(root.column_weights[0], 1)
        self.assertEqual(root.row_weights[1], 1)
        self.assertEqual(window["status_frame"].grid_options["sticky"], "nsew")
        self.assertEqual(window["status_frame"].row_weights[1], 1)
        self.assertEqual(window["status_label"].grid_options["sticky"], "nsew")
        self.assertEqual([child.options.get("text") for child in phone.children], ["Phone"])
        self.assertEqual([child.options.get("text") for child in computer.children], ["MacBook"])
        self.assertEqual(phone.children[0].options["font"], "H5")
        self.assertEqual(window["link_label"].options["width"], 18)
        self.assertEqual(window["status_label"].options["font"], "B5")
        self.assertEqual([button.options["text"] for button in tk.buttons], [
            "Try again", "Remove model copies", "Stop GPU Link"])
        self.assertEqual(window["action_buttons"], tk.buttons)
        self.assertTrue(all(button.grid_options["sticky"] == "ew" for button in tk.buttons))
        self.assertIn("<Configure>", window["status_frame"].bindings)
        window["status_frame"].bindings["<Configure>"](SimpleNamespace(width=600))
        self.assertEqual(window["status_label"].options["wraplength"], 568)
        phone.bindings["<Configure>"](SimpleNamespace(width=200))
        self.assertEqual(phone.children[0].options["wraplength"], 168)

    def test_link_and_status_colors_use_only_the_allowed_states(self):
        self.assertEqual(link._main_window_tone(False, "Phone disconnected; waiting to reconnect"),
                         ("USB-C\nWaiting", link.DIALOG_INK, link.DIALOG_INK))
        self.assertEqual(link._main_window_tone(True, "Answer in progress"),
                         ("USB-C\nConnected", link.DIALOG_SUCCESS, link.DIALOG_INK))
        self.assertEqual(link._main_window_tone(True, "Model copies could not be removed"),
                         ("USB-C\nConnected", link.DIALOG_SUCCESS, link.DIALOG_ERROR))
        self.assertEqual(link._main_window_tone(True, "Model copies were not removed"),
                         ("USB-C\nConnected", link.DIALOG_SUCCESS, link.DIALOG_ERROR))
        self.assertEqual(link._main_window_tone(False, "Phone service unavailable; retrying"),
                         ("USB-C\nNeeds attention", link.DIALOG_ERROR, link.DIALOG_ERROR))
        self.assertEqual(link._main_window_tone(False, "Phone link interrupted; reconnecting"),
                         ("USB-C\nWaiting", link.DIALOG_INK, link.DIALOG_INK))
        self.assertEqual(link._main_window_tone(False, "Failed to reach the phone"),
                         ("USB-C\nNeeds attention", link.DIALOG_ERROR, link.DIALOG_ERROR))
        self.assertEqual(link._main_window_tone(True, "Stopping."),
                         ("USB-C\nStopping", link.DIALOG_INK, link.DIALOG_INK))

    def test_refresh_updates_the_visible_link_and_status(self):
        root, tk = FakeWidget(), FakeTk()
        status = FakeVar("Answer in progress")
        window = link._build_main_window(
            tk, root, status, "MacBook", {"title": "H5", "small": "S5", "body": "B5"},
            lambda: None, lambda: None, lambda: None,
        )
        app = link.Companion.__new__(link.Companion)
        app.online, app.status, app.main_window = True, status, window
        app._refresh_main_window()
        self.assertEqual(window["link_state"].get(), "USB-C\nConnected")
        self.assertEqual(window["link_label"].options["fg"], link.DIALOG_SUCCESS)
        status.set("Phone service unavailable; retrying")
        app.online = False
        app._refresh_main_window()
        self.assertEqual(window["link_state"].get(), "USB-C\nNeeds attention")
        self.assertEqual(window["status_label"].options["fg"], link.DIALOG_ERROR)

    def test_status_change_refreshes_colors_without_waiting_for_tick(self):
        root, tk = FakeWidget(), FakeTk()
        args = SimpleNamespace(adb="unused", serial="fixture", key_dir=Path("unused"),
                               always_allow=False)
        with patch.object(link, "_dialog_fonts", return_value={
                "title": "H5", "small": "S5", "body": "B5"}), \
                patch.object(link, "computer_noun", return_value="MacBook"):
            app = link.Companion(args, root, tk)
        app.online = True
        app.status.set("Model copies could not be removed")
        self.assertEqual(app.main_window["link_state"].get(), "USB-C\nConnected")
        self.assertEqual(app.main_window["link_label"].options["fg"], link.DIALOG_SUCCESS)
        self.assertEqual(app.main_window["status_label"].options["fg"], link.DIALOG_ERROR)
        app.online = False
        app.status.set("Phone service unavailable; retrying")
        self.assertEqual(app.main_window["link_state"].get(), "USB-C\nNeeds attention")
        self.assertEqual(app.main_window["link_label"].options["fg"], link.DIALOG_ERROR)

    def test_slow_usb_check_keeps_status_and_stop_button_responsive(self):
        app, root, tk = self.window_app()
        entered, release = threading.Event(), threading.Event()

        def slow_authorized():
            entered.set()
            release.wait(2)
            return False

        try:
            with patch.object(app.bridge, "authorized", side_effect=slow_authorized):
                started = time.monotonic()
                app.tick()
                self.assertLess(time.monotonic() - started, 0.25)
                self.assertTrue(entered.wait(1))
                app.events.put("Checking the phone again.")
                started = time.monotonic()
                app.tick()
                self.assertLess(time.monotonic() - started, 0.25)
                self.assertEqual(app.status.get(), "Checking the phone again.")
                self.assertEqual([delay for delay, _ in root.scheduled], [100, 100])
                tk.buttons[-1].options["command"]()
                self.assertEqual(app.status.get(), "Stopping.")
                self.assertEqual(app.main_window["link_state"].get(), "USB-C\nStopping")
                self.assertEqual(app.main_window["link_label"].options["fg"], link.DIALOG_INK)
                self.assertFalse(root.destroyed)
        finally:
            release.set()
            if app.link_probe_thread is not None:
                app.link_probe_thread.join(2)
            if app.window_stop_thread is not None:
                app.window_stop_thread.join(2)
        root.scheduled[-1][1]()
        self.assertTrue(root.destroyed)
        self.assertEqual(app.status.get(), "Stopped.")

    def test_stopping_disables_actions_and_ignores_late_commands(self):
        app, root, tk = self.window_app()
        with patch.object(link, "_confirm_remove_model_copies") as confirm:
            app.stop()
            self.assertEqual([button.options["state"] for button in tk.buttons],
                             ["disabled", "disabled", "disabled"])
            self.assertEqual(app.status.get(), "Stopping.")
            app.retry()
            app.remove_model_copies()
            app.stop()
        confirm.assert_not_called()
        self.assertEqual(app.status.get(), "Stopping.")
        self.assertEqual(app.main_window["link_state"].get(), "USB-C\nStopping")
        app.window_stop_thread.join(2)
        root.scheduled[-1][1]()
        self.assertTrue(root.destroyed)

    def test_slow_usb_cleanup_does_not_hold_the_stop_button(self):
        app, root, tk = self.window_app()
        app.bridge.port = 18767
        entered, release = threading.Event(), threading.Event()

        def slow_remove():
            entered.set()
            release.wait(2)
            app.bridge.port = None

        try:
            with patch.object(app.bridge, "remove_own_forward", side_effect=slow_remove):
                started = time.monotonic()
                tk.buttons[-1].options["command"]()
                self.assertLess(time.monotonic() - started, 0.25)
                self.assertTrue(entered.wait(1))
                self.assertEqual(app.status.get(), "Stopping.")
                root.scheduled[-1][1]()
                self.assertFalse(root.destroyed)
                release.set()
                app.window_stop_thread.join(2)
                root.scheduled[-1][1]()
        finally:
            release.set()
        self.assertTrue(root.destroyed)
        self.assertEqual(app.status.get(), "Stopped.")

    def test_window_stop_does_not_report_a_second_cleanup_result(self):
        app, root, _ = self.window_app()
        with patch.object(app.bridge, "remove_own_forward") as remove:
            app.stop()
            app.window_stop_thread.join(2)
            root.scheduled[-1][1]()
            app.run()
        remove.assert_called_once_with()
        self.assertTrue(app.cleanup_ok)

    def test_early_window_exit_waits_for_the_stop_owner(self):
        app, root, _ = self.window_app()
        app.bridge.port = 18767
        entered, release, in_mainloop = threading.Event(), threading.Event(), threading.Event()
        calls = []
        failures = []
        run_thread = None

        def slow_remove():
            calls.append(threading.current_thread().name)
            entered.set()
            release.wait(2)
            app.bridge.port = None

        def run_app():
            try:
                app.run()
            except BaseException as error:
                failures.append(error)

        try:
            with patch.object(app.bridge, "remove_own_forward", side_effect=slow_remove), \
                    patch.object(root, "mainloop", side_effect=in_mainloop.set):
                app.stop()
                self.assertTrue(entered.wait(1))
                run_thread = threading.Thread(target=run_app)
                run_thread.start()
                self.assertTrue(in_mainloop.wait(1))
                run_thread.join(0.05)
                self.assertTrue(run_thread.is_alive())
                self.assertEqual(calls, ["opos-link-stop"])
                release.set()
                run_thread.join(2)
                self.assertFalse(run_thread.is_alive())
        finally:
            release.set()
            if run_thread is not None:
                run_thread.join(2)
            if app.window_stop_thread is not None:
                app.window_stop_thread.join(2)
        self.assertEqual(calls, ["opos-link-stop"])
        self.assertEqual(failures, [])
        self.assertTrue(app.cleanup_ok)

    def test_early_window_exit_does_not_race_after_stop_wait_times_out(self):
        app, root, _ = self.window_app()
        app.bridge.port = 18767
        entered, release = threading.Event(), threading.Event()
        calls = []

        def slow_remove():
            calls.append(threading.current_thread().name)
            entered.set()
            release.wait(2)
            app.bridge.port = None

        try:
            with patch.object(app.bridge, "remove_own_forward", side_effect=slow_remove), \
                    patch.object(link, "WINDOW_STOP_JOIN_BUDGET", 0.01):
                app.stop()
                self.assertTrue(entered.wait(1))
                app.run()
                self.assertTrue(app.window_stop_timed_out)
                self.assertFalse(app.cleanup_ok)
                self.assertEqual(calls, ["opos-link-stop"])
        finally:
            release.set()
            if app.window_stop_thread is not None:
                app.window_stop_thread.join(2)
        self.assertEqual(calls, ["opos-link-stop"])

    def test_incomplete_window_stop_keeps_the_failure_result(self):
        app, root, tk = self.window_app()
        app.bridge.port = 18767
        with patch.object(app.bridge, "remove_own_forward") as remove:
            app.stop()
            app.window_stop_thread.join(2)
            root.scheduled[-1][1]()
            self.assertFalse(app.cleanup_ok)
            self.assertEqual(app.status.get(),
                             "Error: Stop was incomplete. Check the USB link and model server.")
            self.assertFalse(root.destroyed)
            self.assertEqual(app.main_window["link_state"].get(), "USB-C\nNeeds attention")
            self.assertEqual(app.main_window["status_label"].options["fg"], link.DIALOG_ERROR)
            self.assertEqual([button.options["state"] for button in tk.buttons],
                             ["disabled", "disabled", "normal"])
            self.assertEqual(tk.buttons[-1].options["text"], "Close window")
            app.run()
        remove.assert_called_once_with()
        self.assertFalse(app.cleanup_ok)
        tk.buttons[-1].options["command"]()
        self.assertTrue(root.destroyed)

    def test_slow_forward_check_is_read_once_off_the_window_thread(self):
        app, root, _ = self.window_app()
        app.online = True
        app.worker = SimpleNamespace(is_alive=lambda: True)
        entered, release = threading.Event(), threading.Event()
        threads = []

        def slow_forward():
            threads.append(threading.current_thread())
            entered.set()
            release.wait(2)
            return True

        try:
            with patch.object(app.bridge, "authorized", return_value=True), \
                    patch.object(app.bridge, "forward_present", side_effect=slow_forward), \
                    patch.object(link, "model_server_listening", return_value=True):
                app.tick()
                self.assertTrue(entered.wait(1))
                started = time.monotonic()
                app.tick()
                self.assertLess(time.monotonic() - started, 0.25)
                release.set()
                app.link_probe_thread.join(2)
                app.tick()
        finally:
            release.set()
        self.assertTrue(app.online)
        self.assertEqual(len(threads), 1)
        self.assertIsNot(threads[0], threading.current_thread())
        self.assertEqual(root.scheduled[-1][0], 1000)

    def test_finished_model_check_uses_the_background_usb_result(self):
        app, _, _ = self.window_app()
        app.session_pc = object()
        app.preflight_thread = SimpleNamespace(join=lambda timeout: None)
        app.preflight_done = threading.Event()
        app.preflight_done.set()
        app.preflight_cancel = threading.Event()
        app.preflight_result = True
        app._start_worker = lambda pc: setattr(app, "worker", SimpleNamespace(is_alive=lambda: True))
        with patch.object(app.bridge, "authorized", return_value=True), \
                patch.object(app.bridge, "forward_present", return_value=True) as forward:
            app.tick()
            app.link_probe_thread.join(2)
            app.tick()
        self.assertTrue(app.online)
        self.assertEqual(app.status.get(), "Ready for questions on the phone.")
        forward.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

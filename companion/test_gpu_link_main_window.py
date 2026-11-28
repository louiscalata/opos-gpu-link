# SPDX-License-Identifier: Apache-2.0
"""Main-window layout checks without opening a display or contacting a phone."""

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


if __name__ == "__main__":
    unittest.main()

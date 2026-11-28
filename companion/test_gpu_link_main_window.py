# SPDX-License-Identifier: Apache-2.0
"""Main-window layout checks without opening a display or contacting a phone."""

import unittest
from types import SimpleNamespace

import opos_gpu_link as link


class FakeVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class FakeWidget:
    def __init__(self, parent=None, **options):
        self.parent = parent
        self.options = options
        self.children = []
        self.grid_options = None
        self.column_weights = {}
        self.row_weights = {}
        self.bindings = {}
        if parent is not None:
            parent.children.append(self)

    def configure(self, **options):
        self.options.update(options)

    def grid(self, **options):
        self.grid_options = options

    def columnconfigure(self, column, *, weight):
        self.column_weights[column] = weight

    def rowconfigure(self, row, *, weight):
        self.row_weights[row] = weight

    def minsize(self, width, height):
        self.minimum = (width, height)

    def bind(self, event, callback):
        self.bindings[event] = callback


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
        status = FakeVar("Watching for the authorized USB phone")
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
        self.assertEqual(root.column_weights[0], 1)
        self.assertEqual(root.row_weights[1], 1)
        self.assertEqual(window["status_frame"].grid_options["sticky"], "nsew")
        self.assertEqual(window["status_frame"].row_weights[1], 1)
        self.assertEqual(window["status_label"].grid_options["sticky"], "nsew")
        self.assertEqual([label.options.get("text") for label in tk.labels[:2]],
                         ["PHONE", "Phone"])
        self.assertEqual([label.options.get("text") for label in tk.labels[3:5]],
                         ["THIS COMPUTER", "MacBook"])
        self.assertEqual(tk.labels[1].options["font"], "H5")
        self.assertEqual(window["status_label"].options["font"], "B5")
        self.assertEqual([button.options["text"] for button in tk.buttons], [
            "Retry after phone recovery", "Remove model copies", "Stop GPU Link"])
        self.assertTrue(all(button.grid_options["sticky"] == "ew" for button in tk.buttons))
        self.assertIn("<Configure>", window["status_frame"].bindings)
        window["status_frame"].bindings["<Configure>"](SimpleNamespace(width=600))
        self.assertEqual(window["status_label"].options["wraplength"], 576)

    def test_link_and_status_colors_use_only_the_allowed_states(self):
        self.assertEqual(link._main_window_tone(False, "Phone disconnected; waiting to reconnect"),
                         ("USB-C\nWaiting", link.DIALOG_INK, link.DIALOG_INK))
        self.assertEqual(link._main_window_tone(True, "Answer in progress"),
                         ("USB-C\nConnected", link.DIALOG_SUCCESS, link.DIALOG_INK))
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


if __name__ == "__main__":
    unittest.main()

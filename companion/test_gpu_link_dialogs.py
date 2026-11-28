# SPDX-License-Identifier: Apache-2.0
"""Tk dialog copy and behavior checks without a display, phone, or model server."""

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import opos_gpu_link as link


class FakeWidget:
    def __init__(self, parent, **options):
        self.parent = parent
        self.options = options
        self.pack_options = None
        self.focused = False

    def pack(self, **options):
        self.pack_options = options

    def configure(self, **options):
        self.options.update(options)

    def focus_set(self):
        self.focused = True
        self.parent.focused_widget = self

    def invoke(self):
        if self.options.get("state") != "disabled":
            self.options["command"]()


class FakeWindow:
    def __init__(self, parent):
        self.parent = parent
        self.options = {}
        self.after_calls = {}
        self.bindings = {}
        self.protocols = {}
        self.destroyed = False
        self.title_text = None
        self.focused_widget = None
        self.next_after_id = 0

    def title(self, value):
        self.title_text = value

    def transient(self, _parent):
        pass

    def grab_set(self):
        pass

    def configure(self, **options):
        self.options.update(options)

    def after(self, delay, callback):
        self.next_after_id += 1
        timer_id = f"after-{self.next_after_id}"
        self.after_calls.setdefault(delay, []).append((timer_id, callback))
        return timer_id

    def after_cancel(self, timer_id):
        for callbacks in self.after_calls.values():
            callbacks[:] = [(scheduled, callback) for scheduled, callback in callbacks
                            if scheduled != timer_id]

    def run_after(self, delay):
        _, callback = self.after_calls[delay].pop(0)
        callback()

    def pending_after_count(self):
        return sum(len(callbacks) for callbacks in self.after_calls.values())

    def focus_get(self):
        return self.focused_widget

    def bind(self, event, callback):
        self.bindings[event] = callback

    def protocol(self, name, callback):
        self.protocols[name] = callback

    def destroy(self):
        self.destroyed = True


class FakeTk:
    def __init__(self):
        self.labels = []
        self.buttons = []
        self.windows = []

    def Toplevel(self, parent):
        window = FakeWindow(parent)
        self.windows.append(window)
        return window

    def Label(self, parent, **options):
        label = FakeWidget(parent, **options)
        self.labels.append(label)
        return label

    def Button(self, parent, **options):
        button = FakeWidget(parent, **options)
        self.buttons.append(button)
        return button


class DialogTests(unittest.TestCase):
    FONTS = {"title": "H5 font", "small": "S5 font", "body": "B5 font"}

    def app(self, root, tk, now, args=None, attached=None):
        return SimpleNamespace(headless=False, root=root, tk=tk,
                               args=args or SimpleNamespace(), clock=lambda: now[0],
                               link_present=lambda: attached[0] if attached else True)

    def test_h5_s5_b5_tokens_and_installed_font_preference(self):
        self.assertEqual(link.DIALOG_TYPE, {
            "H5": {"size": 21, "weight": "semibold", "leading": 1.15, "tracking": -0.01},
            "S5": {"size": 11, "weight": "normal", "leading": 1.25, "tracking": 0.02, "tnum": True},
            "B5": {"size": 17, "weight": "normal", "leading": 1.35, "tracking": 0.0},
        })
        self.assertEqual((link.DIALOG_INK, link.DIALOG_PAPER, link.DIALOG_ERROR),
                         ("#000000", "#FFFFFF", "#B00000"))
        specs = link._dialog_font_specs(
            {"Source Serif 4 Subhead Semibold", "Source Serif 4", "Inter Medium"},
            "Tk heading", "Tk text")
        self.assertEqual(specs, {"title": ("Source Serif 4 Subhead Semibold", 21, "normal"),
                                 "small": ("Inter Medium", 11, "normal"),
                                 "body": ("Source Serif 4", 17, "normal")})
        public = link._dialog_font_specs({"Newsreader", "Inter"}, "Tk heading", "Tk text")
        self.assertEqual(public, {"title": ("Newsreader", 21, "bold"),
                                  "small": ("Inter", 11, "normal"),
                                  "body": ("Newsreader", 17, "normal")})
        fallback = link._dialog_font_specs(set(), "Tk heading", "Tk text")
        self.assertEqual(fallback, {"title": ("Tk heading", 21, "bold"),
                                    "small": ("Tk text", 11, "normal"),
                                    "body": ("Tk text", 17, "normal")})

    def test_identity_lines_only_use_supplied_phone_and_gpu_names(self):
        args = SimpleNamespace(phone_label=" Pixel 9 ",
                               runtime=SimpleNamespace(gpu={"name": "Apple M5 Pro", "backend": "metal"}))
        self.assertEqual(link._permission_identity_lines(args),
                         ["Phone: Pixel 9", "GPU: Apple M5 Pro"])
        self.assertEqual(link._permission_identity_lines(SimpleNamespace()), [])
        generic = SimpleNamespace(phone_label="OPOS phone",
                                  runtime=SimpleNamespace(gpu={"name": "Apple GPU", "backend": "metal"}))
        self.assertEqual(link._permission_identity_lines(generic), [])
        mac = SimpleNamespace(runtime=SimpleNamespace(gpu={"name": "Mac", "backend": "metal"}))
        self.assertEqual(link._permission_identity_lines(mac), [])

        cpu = SimpleNamespace(runtime=SimpleNamespace(gpu={"name": "CPU only", "backend": "cpu"}))
        self.assertEqual(link._permission_identity_lines(cpu), [])

    def test_permission_copy_typography_and_safe_default_after_700_ms(self):
        now = [0.0]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            self.assertEqual(top.title_text, "Let this phone use your MacBook's GPU?")
            self.assertEqual(top.options["bg"], link.DIALOG_PAPER)
            self.assertEqual([label.options["text"] for label in tk.labels], [
                "Let this phone use your MacBook's GPU?",
                "The phone can use this MacBook's GPU while the cable is plugged in.",
                "This MacBook can see your questions and the answers.",
                "A copy of the model file stays on this MacBook until you remove it.",
                "Unplug to pause. Access ends after 2 minutes unplugged or when you choose Stop GPU Link.",
            ])
            self.assertEqual([label.options["font"] for label in tk.labels],
                             ["H5 font", "B5 font", "B5 font", "B5 font", "S5 font"])
            self.assertTrue(all(label.options["fg"] == link.DIALOG_INK
                                and label.options["bg"] == link.DIALOG_PAPER for label in tk.labels))
            allow, deny = tk.buttons
            self.assertEqual((allow.options["text"], deny.options["text"]), ("Allow this phone", "Not now"))
            self.assertEqual((allow.options["state"], deny.options["state"]),
                             ("disabled", "normal"))
            self.assertTrue(all(button.options["font"] == "S5 font"
                                and button.options["fg"] == link.DIALOG_INK
                                and button.options["bg"] == link.DIALOG_PAPER for button in tk.buttons))
            allow.options["command"]()  # Even a direct callback is ignored during debounce.
            self.assertFalse(top.destroyed)
            now[0] = 0.7
            top.run_after(700)
            self.assertEqual((allow.options["state"], deny.options["state"]),
                             ("normal", "normal"))
            self.assertTrue(deny.focused)
            top.bindings["<Return>"](None)
            self.assertTrue(top.destroyed)
            self.assertEqual(top.pending_after_count(), 0)

        root.wait_window = wait_window
        app = self.app(root, tk, now)
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS), \
                patch.object(link, "computer_noun", return_value="MacBook"):
            self.assertFalse(link.Companion.permission(app))

    def test_allow_rechecks_attachment_and_escape_denies(self):
        for action, attached_at_finish, expected in (("Allow", True, True),
                                                      ("Allow", False, False),
                                                      ("Escape", True, False)):
            with self.subTest(action=action, attached=attached_at_finish):
                now = [0.0]
                attached = [True]
                tk = FakeTk()
                root = SimpleNamespace()

                def wait_window(top):
                    now[0] = 0.8
                    top.run_after(700)
                    attached[0] = attached_at_finish
                    if action == "Allow":
                        tk.buttons[0].invoke()
                    else:
                        top.bindings["<Escape>"](None)
                    self.assertTrue(top.destroyed)

                root.wait_window = wait_window
                with patch.object(link, "_dialog_fonts", return_value=self.FONTS):
                    self.assertEqual(link.Companion.permission(
                        self.app(root, tk, now, attached=attached)), expected)

    def test_permission_early_cancel_clears_both_timers(self):
        now = [0.0]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            self.assertEqual(top.pending_after_count(), 2)
            top.bindings["<Escape>"](None)
            self.assertTrue(top.destroyed)
            self.assertEqual(top.pending_after_count(), 0)

        root.wait_window = wait_window
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS), \
                patch.object(link, "computer_noun", return_value="MacBook"):
            self.assertFalse(link.Companion.permission(self.app(root, tk, now)))

    def test_permission_return_accepts_focused_allow_after_guard(self):
        now = [0.0]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            now[0] = 0.8
            top.run_after(700)
            tk.buttons[0].focus_set()
            self.assertEqual(top.bindings["<Return>"](None), "break")
            self.assertTrue(top.destroyed)
            self.assertEqual(top.pending_after_count(), 0)

        root.wait_window = wait_window
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS), \
                patch.object(link, "computer_noun", return_value="MacBook"):
            self.assertTrue(link.Companion.permission(self.app(root, tk, now)))

    def test_pairing_dialog_uses_same_fonts_and_red_timeout(self):
        now = [0.0]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            self.assertEqual(top.title_text, "Pair this MacBook?")
            self.assertEqual(top.options["bg"], link.DIALOG_PAPER)
            self.assertEqual([label.options["text"] for label in tk.labels],
                             ["Pair this MacBook?",
                              "Compare this code with the phone before you allow.",
                              "Pairing code", "123 456", "60 seconds left",
                              "If allowed, this MacBook can see your questions and the answers. A model file stays here.",
                              "On the phone, tap Allow this MacBook."])
            self.assertEqual([label.options["font"] for label in tk.labels],
                             ["H5 font", "B5 font", "S5 font", "H5 font", "S5 font", "B5 font", "S5 font"])
            self.assertTrue(all(label.options["fg"] == link.DIALOG_INK
                                and label.options["bg"] == link.DIALOG_PAPER for label in tk.labels))
            self.assertEqual(tk.buttons[0].options["font"], "S5 font")
            self.assertEqual(tk.buttons[0].options["text"], "Not now")
            self.assertTrue(tk.buttons[0].focused)
            now[0] = 61.0
            top.run_after(750)
            self.assertEqual(tk.labels[6].options["text"],
                             "Error: Pairing expired. Wait for a new code on the phone.")
            self.assertEqual(tk.labels[6].options["fg"], link.DIALOG_ERROR)
            self.assertEqual(tk.labels[4].options["text"], "Expired")
            self.assertEqual(tk.labels[4].options["fg"], link.DIALOG_ERROR)
            top.run_after(5000)
            self.assertTrue(top.destroyed)
            self.assertEqual(top.pending_after_count(), 0)

        root.wait_window = wait_window
        app = self.app(root, tk, now)
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS), \
                patch.object(link, "computer_noun", return_value="MacBook"), \
                patch.object(link.proto, "code", return_value="123456"):
            self.assertFalse(link.Companion.wait_for_phone_allow(
                app, SimpleNamespace(label="fixture", key=b"fixture")))

    def test_pairing_early_cancel_clears_probe_timer(self):
        now = [0.0]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            self.assertEqual(top.pending_after_count(), 1)
            top.bindings["<Escape>"](None)
            self.assertTrue(top.destroyed)
            self.assertEqual(top.pending_after_count(), 0)

        root.wait_window = wait_window
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS), \
                patch.object(link, "computer_noun", return_value="MacBook"), \
                patch.object(link.proto, "code", return_value="123456"):
            self.assertFalse(link.Companion.wait_for_phone_allow(
                self.app(root, tk, now), SimpleNamespace(label="fixture", key=b"fixture")))

    def test_pairing_disconnect_clears_countdown_and_keeps_red_error_readable(self):
        now = [0.0]
        attached = [True]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            attached[0] = False
            top.run_after(750)
            self.assertEqual(tk.labels[4].options["text"], "")
            self.assertEqual(tk.labels[6].options["text"],
                             "Error: Phone not ready. Check the cable and USB access.")
            self.assertEqual(tk.labels[6].options["fg"], link.DIALOG_ERROR)
            self.assertEqual(top.pending_after_count(), 1)
            tk.buttons[0].invoke()
            self.assertTrue(top.destroyed)
            self.assertEqual(top.pending_after_count(), 0)

        root.wait_window = wait_window
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS), \
                patch.object(link, "computer_noun", return_value="MacBook"), \
                patch.object(link.proto, "code", return_value="123456"):
            self.assertFalse(link.Companion.wait_for_phone_allow(
                self.app(root, tk, now, attached=attached),
                SimpleNamespace(label="fixture", key=b"fixture")))

    def test_remove_model_copies_is_styled_and_defaults_to_not_now(self):
        now = [0.0]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            self.assertEqual(top.title_text, "Remove model copies?")
            self.assertEqual(top.options["bg"], link.DIALOG_PAPER)
            self.assertEqual([label.options["font"] for label in tk.labels],
                             ["H5 font", "B5 font", "S5 font"])
            self.assertEqual([button.options["text"] for button in tk.buttons],
                             ["Remove copies", "Not now"])
            remove, deny = tk.buttons
            remove.options["command"]()  # The 700 ms guard rejects direct activation.
            self.assertFalse(top.destroyed)
            now[0] = 0.7
            top.run_after(700)
            self.assertTrue(deny.focused)
            top.bindings["<Return>"](None)
            self.assertTrue(top.destroyed)
            self.assertEqual(top.pending_after_count(), 0)

        root.wait_window = wait_window
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS):
            self.assertFalse(link._confirm_remove_model_copies(
                root, Path("/models"), tk, clock=lambda: now[0]))

    def test_remove_copies_return_uses_focused_button(self):
        now = [0.0]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            now[0] = 0.8
            top.run_after(700)
            tk.buttons[0].focus_set()
            self.assertEqual(top.bindings["<Return>"](None), "break")
            self.assertTrue(top.destroyed)
            self.assertEqual(top.pending_after_count(), 0)

        root.wait_window = wait_window
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS):
            self.assertTrue(link._confirm_remove_model_copies(
                root, Path("/models"), tk, clock=lambda: now[0]))

    def test_remove_copies_early_close_clears_timer(self):
        now = [0.0]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            self.assertEqual(top.pending_after_count(), 1)
            top.protocols["WM_DELETE_WINDOW"]()
            self.assertTrue(top.destroyed)
            self.assertEqual(top.pending_after_count(), 0)

        root.wait_window = wait_window
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS):
            self.assertFalse(link._confirm_remove_model_copies(
                root, Path("/models"), tk, clock=lambda: now[0]))


if __name__ == "__main__":
    unittest.main()

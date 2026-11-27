# SPDX-License-Identifier: Apache-2.0
"""Tk dialog copy and behavior checks without a display, phone, or model server."""

import unittest
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

    def title(self, value):
        self.title_text = value

    def transient(self, _parent):
        pass

    def grab_set(self):
        pass

    def configure(self, **options):
        self.options.update(options)

    def after(self, delay, callback):
        self.after_calls.setdefault(delay, []).append(callback)

    def run_after(self, delay):
        self.after_calls[delay].pop(0)()

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
            "H5": {"size": 21, "weight": "bold", "leading": 1.15, "tracking": -0.01},
            "S5": {"size": 11, "weight": "normal", "leading": 1.25, "tracking": 0.02},
            "B5": {"size": 17, "weight": "normal", "leading": 1.35, "tracking": 0.0},
        })
        self.assertEqual((link.DIALOG_INK, link.DIALOG_PAPER, link.DIALOG_ERROR),
                         ("#000000", "#FFFFFF", "#B00000"))
        specs = link._dialog_font_specs(
            {"Newsreader", "Inter Tight", "Inter Tight Medium", "Inter"}, "Tk heading", "Tk text")
        self.assertEqual(specs, {"title": ("Newsreader", 21, "bold"),
                                 "small": ("Inter Tight Medium", 11, "normal"),
                                 "body": ("Inter Tight", 17, "normal")})
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
        cpu = SimpleNamespace(runtime=SimpleNamespace(gpu={"name": "CPU only", "backend": "cpu"}))
        self.assertEqual(link._permission_identity_lines(cpu), [])

    def test_permission_copy_typography_and_safe_default_after_700_ms(self):
        now = [0.0]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            self.assertEqual(top.title_text, "Let this phone use your GPU?")
            self.assertEqual(top.options["bg"], link.DIALOG_PAPER)
            self.assertEqual([label.options["text"] for label in tk.labels], [
                "Let this phone use your GPU?",
                "A language model will run on this computer's GPU while the phone is plugged in.",
                "This computer will see the questions and the answers.",
                "A copy of the model file stays on this computer until it is removed.",
                "Unplug to pause. Access ends 2 minutes after unplug, or when you choose Stop GPU Link.",
            ])
            self.assertEqual([label.options["font"] for label in tk.labels],
                             ["H5 font", "B5 font", "B5 font", "B5 font", "S5 font"])
            self.assertTrue(all(label.options["fg"] == link.DIALOG_INK
                                and label.options["bg"] == link.DIALOG_PAPER for label in tk.labels))
            allow, deny = tk.buttons
            self.assertEqual((allow.options["text"], deny.options["text"]), ("Allow", "Not now"))
            self.assertEqual((allow.options["state"], deny.options["state"]),
                             ("disabled", "disabled"))
            self.assertTrue(all(button.options["font"] == "S5 font"
                                and button.options["fg"] == link.DIALOG_INK
                                and button.options["bg"] == link.DIALOG_PAPER for button in tk.buttons))
            allow.options["command"]()  # Even a direct callback is ignored during debounce.
            top.bindings["<Escape>"](None)
            self.assertFalse(top.destroyed)
            now[0] = 0.7
            top.run_after(700)
            self.assertEqual((allow.options["state"], deny.options["state"]),
                             ("normal", "normal"))
            self.assertTrue(deny.focused)
            top.bindings["<Return>"](None)
            self.assertTrue(top.destroyed)

        root.wait_window = wait_window
        app = self.app(root, tk, now)
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS):
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

    def test_pairing_dialog_uses_same_fonts_and_red_timeout(self):
        now = [0.0]
        tk = FakeTk()
        root = SimpleNamespace()

        def wait_window(top):
            self.assertEqual(top.title_text, "Confirm on the phone")
            self.assertEqual(top.options["bg"], link.DIALOG_PAPER)
            self.assertEqual([label.options["text"] for label in tk.labels],
                             ["Compare on the phone: 123 456",
                              "Tap Allow on the phone within 60 seconds."])
            self.assertEqual([label.options["font"] for label in tk.labels],
                             ["H5 font", "B5 font"])
            self.assertTrue(all(label.options["fg"] == link.DIALOG_INK
                                and label.options["bg"] == link.DIALOG_PAPER for label in tk.labels))
            self.assertEqual(tk.buttons[0].options["font"], "S5 font")
            now[0] = 61.0
            top.run_after(750)
            self.assertEqual(tk.labels[1].options["text"],
                             "Phone Allow was not confirmed. Pairing was not saved.")
            self.assertEqual(tk.labels[1].options["fg"], link.DIALOG_ERROR)
            top.run_after(1500)
            self.assertTrue(top.destroyed)

        root.wait_window = wait_window
        app = self.app(root, tk, now)
        with patch.object(link, "_dialog_fonts", return_value=self.FONTS), \
                patch.object(link.proto, "code", return_value="123456"):
            self.assertFalse(link.Companion.wait_for_phone_allow(
                app, SimpleNamespace(label="fixture", key=b"fixture")))


if __name__ == "__main__":
    unittest.main()

# SPDX-License-Identifier: Apache-2.0
"""The phone-service web page names the paired computer as the app does: MacBook, Mac or PC
from its display name, else "computer". The saved pairing label and the API's placeholder
place ("on the PC's GPU", which the app matches) stay as they are.

No test here opens a socket: every test runs with outgoing connections refused, and the page
script runs in node against a stub DOM whose fetch never answers."""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opos import gpu_link  # noqa: E402

PAGE = ROOT / "src" / "opos" / "ai_page.py"
LINK_API = ROOT / "src" / "opos" / "link_api.py"
DISPLAY = {"OPOS_GPU_LINK_PC_DISPLAY": "M5 Pro PC=M5 Pro MacBook Pro"}
PC_WORD = re.compile(r"\bPCs?\b")


def _refuse(*_args, **_kwargs):
    raise AssertionError("tests must not open a network connection")


class NoNetwork(unittest.TestCase):
    def setUp(self):
        for target in ("connect", "connect_ex"):
            patcher = mock.patch.object(socket.socket, target, _refuse)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = mock.patch.object(socket, "create_connection", _refuse)
        patcher.start()
        self.addCleanup(patcher.stop)


class ComputerNounTest(NoNetwork):
    def test_mac_display_names(self):
        with mock.patch.dict(os.environ, DISPLAY):
            self.assertEqual(gpu_link.computer_noun("M5 Pro PC"), "MacBook")  # saved label, shown as a MacBook
        self.assertEqual(gpu_link.computer_noun("Studio Mac Studio"), "Mac")
        self.assertEqual(gpu_link.computer_noun("iMac 24"), "Mac")
        self.assertEqual(gpu_link.computer_noun("MBP 16"), "MacBook")

    def test_other_paired_computers_are_pcs_and_none_is_computer(self):
        with mock.patch.dict(os.environ, {"OPOS_GPU_LINK_PC_DISPLAY": ""}):
            self.assertEqual(gpu_link.computer_noun("M5 Pro PC"), "PC")  # no display name: the label decides
            self.assertEqual(gpu_link.computer_noun("RTX 5080 PC"), "PC")
            self.assertEqual(gpu_link.computer_noun("Machine"), "PC")
            for none in (None, "", "   ", 7):
                self.assertEqual(gpu_link.computer_noun(none), "computer")

    def test_saved_answer_noun(self):
        with mock.patch.dict(os.environ, DISPLAY):
            self.assertEqual(gpu_link.answer_noun("RTX 5080 PC", "M5 Pro PC"), "PC")
            self.assertEqual(gpu_link.answer_noun("M5 Pro PC", "RTX 5080 PC"), "MacBook")
            for empty in (None, "", "  ", "on the PC's GPU", " on the PC's GPU "):
                self.assertEqual(gpu_link.answer_noun(empty, "M5 Pro PC"), "MacBook")
                self.assertEqual(gpu_link.answer_noun(empty, None), "computer")

    def test_title(self):
        self.assertEqual([gpu_link.computer_title(n) for n in ("computer", "MacBook", "Mac", "PC", "")],
                         ["Computer", "MacBook", "Mac", "PC", "Computer"])

    def test_saved_label_is_only_read(self):
        with mock.patch.dict(os.environ, DISPLAY):
            label = "M5 Pro PC"
            gpu_link.computer_noun(label)
            self.assertEqual(label, "M5 Pro PC")
            self.assertEqual(gpu_link.display_label(label), "M5 Pro MacBook Pro")


def _constants(path: Path, name: str | None = None) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = {id(node.body[0].value) for node in ast.walk(tree)
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            and node.body and isinstance(node.body[0], ast.Expr) and isinstance(node.body[0].value, ast.Constant)}
    found = []
    for node in ast.walk(tree):
        if name is not None and isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return [(node.lineno, node.value.value)]
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
            found.append((node.lineno, node.value))
    if name is not None:
        raise AssertionError(f"{name} not found in {path.name}")
    return found


class ScreenWordsTest(NoNetwork):
    PLACEHOLDER = "on the PC's GPU"  # API contract; the app's PaneKeys.shownWhere matches it

    def test_no_page_or_api_string_calls_the_computer_a_pc(self):
        found = []
        for path in (PAGE, LINK_API):
            for line, value in _constants(path):
                if value == self.PLACEHOLDER:
                    continue
                if path == PAGE and value.startswith("\nfunction G(id)"):
                    value = re.sub(r'"on the PC\'s GPU"', "", value)  # the script's placeholder match
                    value = re.sub(r"//[^\n]*", "", value)
                    value = value.replace("return 'PC';", "")  # nounOf's answer for a non-Mac
                if PC_WORD.search(value):
                    hits = [m.group(0) for m in PC_WORD.finditer(value)]
                    found.append(f"{path.name}:{line}: {hits} in {value[:50]!r}")
        self.assertEqual(found, [])

    def test_page_script_uses_the_same_mac_patterns_as_the_service(self):
        """nounOf in the page mirrors computer_noun; keep the two from drifting apart."""
        script = _constants(PAGE, "_SCRIPT")[0][1]
        found = re.findall(r"/(\\b\(\?:[^/]*)/i\.test\(label\)", script)
        self.assertEqual(found, [gpu_link._MACBOOK.pattern, gpu_link._MAC.pattern])
        self.assertTrue(gpu_link._MACBOOK.flags & re.I and gpu_link._MAC.flags & re.I)

    def test_placeholder_place_is_unchanged_in_the_api(self):
        self.assertIn(f'PC_WHERE = "{self.PLACEHOLDER}"', PAGE.read_text(encoding="utf-8"))
        self.assertEqual(LINK_API.read_text(encoding="utf-8").count(f'"{self.PLACEHOLDER}"'), 2)


NODE_HARNESS = r"""
'use strict';
const fs=require('node:fs'),vm=require('node:vm');
const [script,snapshotsPath,search]=process.argv.slice(2).map(p=>fs.readFileSync(p,'utf8'));
const snapshots=JSON.parse(snapshotsPath);
const nodes=new Map();
class El{constructor(id){this.id=id;this.text='';this.hidden=false;this.dataset={};this.attrs={};this.children=[];this.parentNode=null;this.value='';this.style={};this.classList={toggle(){},add(){},remove(){}}}
 set textContent(v){this.text=String(v);this.children=[]} get textContent(){return this.text}
 set innerHTML(v){throw new Error('no markup')}
 appendChild(c){c.parentNode=this;this.children.push(c);return c} insertBefore(c){return this.appendChild(c)}
 remove(){} setAttribute(k,v){this.attrs[k]=String(v)} getAttribute(k){return this.attrs[k]} removeAttribute(k){delete this.attrs[k]}
 addEventListener(){} focus(){} querySelector(){return null} querySelectorAll(){return []} scrollIntoView(){}}
const get=id=>{if(!nodes.has(id))nodes.set(id,new El(id));return nodes.get(id)};
const document={hidden:false,documentElement:new El('html'),getElementById:get,createElement:t=>new El(''),
 activeElement:null,querySelector:()=>({content:'fixture-token'}),addEventListener(){}};
const refuse=name=>function(){throw new Error(name+' is not allowed in tests')};
const ctx=vm.createContext({document,location:{search},URLSearchParams,AbortController,
 WebSocket:refuse('WebSocket'),EventSource:refuse('EventSource'),XMLHttpRequest:refuse('XMLHttpRequest'),
 performance:{now:()=>0},setTimeout:()=>0,clearTimeout(){},console,
 fetch:()=>new Promise(()=>{})});  // never answers: no request leaves this process
vm.runInContext(script,ctx);
const out=[];
for(const s of snapshots){
 vm.runInContext('draw('+JSON.stringify(s)+')',ctx);
 out.push({title:get('gpu-title').text,disclosure:get('gpu-disclosure').text,aria:get('gpu-answer').attrs['aria-label'],
  reopen:get('reopen').text,forget:get('forget').text,speed:get('gpu-speed').text,model:get('gpu-model').text,
  enrol:get('enrol-text').text,ask:get('ask').text});
}
process.stdout.write(JSON.stringify(out));
"""


def _snapshot(pc=None, pending=None):
    link = {"pc": pc, "pending": pending, "enrol": "open", "model": None}
    return {"boot": "b", "rev": 1, "presets": [], "models": [],
            "phone": {"model": "", "where": "on this phone", "ready": False, "answer": None, "live_speed": None},
            "gpu": {"model": "", "where": "on the PC's GPU", "ready": False, "answer": None, "link": link}}


def _pc(label):
    return {"label": label, "live": False, "state": "idle", "models": []}


@unittest.skipIf(shutil.which("node") is None, "needs node to run the page script")
class PageScriptTest(NoNetwork):
    def run_page(self, snapshots, search=""):
        script = _constants(PAGE, "_SCRIPT")[0][1]
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for name, value in (("harness.js", NODE_HARNESS), ("page.js", script),
                                ("snapshots.json", json.dumps(snapshots)), ("search.txt", search)):
                path = Path(tmp) / name
                path.write_text(value, encoding="utf-8")
                paths.append(str(path))
            done = subprocess.run(["node", *paths], capture_output=True, text=True, timeout=30,
                                  stdin=subprocess.DEVNULL, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_paired_macbook(self):
        shown = self.run_page([_snapshot(_pc("M5 Pro MacBook Pro"))])[0]
        self.assertEqual(shown["title"], "MacBook GPU")
        self.assertEqual(shown["disclosure"], "This MacBook can see what you ask here.")
        self.assertEqual(shown["aria"], "MacBook GPU answer")
        self.assertEqual(shown["forget"], "Forget this MacBook")
        self.assertEqual(shown["reopen"], "")  # the static "Allow computer requests again" is left alone
        self.assertIn("Waiting for the MacBook", shown["speed"])
        self.assertNotIn("PC", json.dumps(shown))

    def test_desktop_mac(self):
        shown = self.run_page([_snapshot(_pc("Mac Studio"))])[0]
        self.assertEqual(shown["title"], "Mac GPU")

    def test_nothing_paired_says_computer_and_placeholder_is_worded(self):
        shown = self.run_page([_snapshot()])[0]
        self.assertEqual(shown["title"], "Computer GPU")
        self.assertEqual(shown["forget"], "Forget this computer")
        self.assertIn("Waiting for the computer", shown["speed"])
        self.assertIn("on the computer's GPU", shown["model"])
        self.assertNotIn("PC", json.dumps(shown))

    def test_paired_windows_pc_still_says_pc(self):
        shown = self.run_page([_snapshot(_pc("RTX 5080 PC"))])[0]
        self.assertEqual(shown["title"], "PC GPU")
        self.assertIn("Waiting for the PC", shown["speed"])

    def test_noun_follows_pairing_changes(self):
        shown = self.run_page([_snapshot(_pc("RTX 5080 PC")), _snapshot(_pc("M5 Pro MacBook Pro")), _snapshot()])
        keys = ("title", "disclosure", "forget", "aria")
        self.assertEqual([tuple(s[k] for k in keys) for s in shown], [
            ("PC GPU", "This PC can see what you ask here.", "Forget this PC", "PC GPU answer"),
            ("MacBook GPU", "This MacBook can see what you ask here.", "Forget this MacBook", "MacBook GPU answer"),
            ("Computer GPU", "This computer can see what you ask here.", "Forget this computer", "Computer GPU answer"),
        ])
        self.assertIn("Waiting for the computer", shown[2]["speed"])

    def test_closed_pairing_and_gpu_only_page(self):
        snap = _snapshot()
        snap["gpu"]["link"]["enrol"] = "closed"
        self.assertIn("Computer requests are closed.", self.run_page([snap])[0]["speed"])
        shown = self.run_page([_snapshot(_pc("M5 Pro MacBook Pro"))], "?pane=gpu")[0]
        self.assertEqual(shown["ask"], "Ask MacBook GPU models")

    def test_a_saved_answer_names_the_computer_that_wrote_it(self):
        snap = _snapshot(_pc("M5 Pro MacBook Pro"))
        snap["gpu"]["answer"] = {"id": "a1", "state": "failed", "error": "", "where": "RTX 5080 PC", "model": "m",
                                 "question": "q", "text": "", "finish": None}
        self.assertIn("The PC could not finish the answer.", self.run_page([snap])[0]["speed"])

    def test_pending_pairing_uses_the_requesting_computers_noun(self):
        shown = self.run_page([_snapshot(None, {"label": "M5 Pro MacBook Pro", "code": "123456"})])[0]
        self.assertIn("This MacBook will see what you ask", shown["enrol"])
        shown = self.run_page([_snapshot(None, {"label": "Studio", "code": "123456"})])[0]
        self.assertIn("This PC will see what you ask", shown["enrol"])


try:
    from opos import ai_page
    from tests import test_ai_page as _page
except ImportError:  # the repo copy has no host app
    _page = None


@unittest.skipIf(_page is None, "needs the host app (ai_model_pool)")
class SnapshotTest(NoNetwork):
    if _page is not None:
        setUp_page = _page.AiPage.setUp
        close_workers = _page.AiPage.close_workers

    def setUp(self):
        super().setUp()
        self.setUp_page()

    def test_snapshot_keys_and_placeholder_are_unchanged(self):
        snap = ai_page.snapshot()
        self.assertEqual(set(snap), {"boot", "rev", "phone", "gpu", "models", "presets"})
        self.assertEqual(snap["gpu"]["where"], "on the PC's GPU")


if __name__ == "__main__":
    unittest.main()

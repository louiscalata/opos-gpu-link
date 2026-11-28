# SPDX-License-Identifier: Apache-2.0
"""Check the fallback page's speed, failure, and locked words without a phone or socket."""

import json
import shutil
import subprocess
import unittest

from tests.test_computer_words import NoNetwork, PAGE, _constants, _snapshot


NODE_HARNESS = r"""
'use strict';
const fs=require('node:fs'),vm=require('node:vm');
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const nodes=new Map();
const statusWrites=[];
const noticeTimers=[];
class El{
 constructor(id){this.id=id;this.text='';this.hidden=false;this.dataset={};this.attrs={};
  this.children=[];this.value='';this.style={};this.scrollHeight=0;this.clientHeight=0;
  this.scrollTop=0;this.classList={toggle(){},add(){},remove(){}}}
 set textContent(v){this.text=String(v);this.children=[];
  if(this.id==='announcement')statusWrites.push(this.text)} get textContent(){return this.text}
 appendChild(c){this.children.push(c);c.parentNode=this;return c} insertBefore(c){return this.appendChild(c)}
 setAttribute(k,v){this.attrs[k]=String(v)} getAttribute(k){return this.attrs[k]}
 remove(){} focus(){} addEventListener(){}
}
const get=id=>{if(!nodes.has(id))nodes.set(id,new El(id));return nodes.get(id)};
get('home-parent').appendChild(get('home'));
const document={hidden:false,documentElement:new El('html'),getElementById:get,
 createElement:()=>new El(''),activeElement:null,
 querySelector:()=>({content:'fixture-token'}),addEventListener(){}};
const refuse=name=>function(){throw new Error(name+' is not allowed in tests')};
const ctx=vm.createContext({document,location:{search:input.search||''},URLSearchParams,AbortController,
 WebSocket:refuse('WebSocket'),EventSource:refuse('EventSource'),XMLHttpRequest:refuse('XMLHttpRequest'),
 performance:{now:()=>0},setTimeout:(fn,delay)=>{if(delay===50)noticeTimers.push(fn);return 0},
 clearTimeout(){},console,
 fetch:()=>{if(input.duringRequest)vm.runInContext(input.duringRequest,ctx);
  return input.reply?Promise.resolve({status:input.reply.status,
   json:()=>Promise.resolve(input.reply.body)}):new Promise(()=>{})}});
(async()=>{
 vm.runInContext(input.script,ctx);
 vm.runInContext('draw('+JSON.stringify(input.snapshot)+')',ctx);
 if(input.reply){vm.runInContext('request()',ctx);await new Promise(setImmediate)}
 const responseState={askQueued:vm.runInContext('askQueued',ctx),
  queued:vm.runInContext('queue.length',ctx),controlsHidden:get('controls').hidden,
  phoneRootHidden:get('phone-extra').hidden,pcRootHidden:get('pc-extra').hidden};
 if(input.after)vm.runInContext('draw('+JSON.stringify(input.after)+')',ctx);
 if(input.afterAction)vm.runInContext(input.afterAction,ctx);
 while(noticeTimers.length)noticeTimers.shift()();
 process.stdout.write(JSON.stringify({phoneSpeed:get('phone-speed').text,
  gpuSpeed:get('gpu-speed').text,m1Speed:get('m1-speed').text,g1Speed:get('g1-speed').text,
  phoneState:get('phone-state').text,m1State:get('m1-state').text,g1State:get('g1-state').text,
  announcement:get('announcement').text,statusWrites,
  error:get('err').text,controlsHidden:get('controls').hidden,
  askDisabled:get('ask').disabled,askQueued:vm.runInContext('askQueued',ctx),
  queued:vm.runInContext('queue.length',ctx),responseState}));
})().catch(err=>{console.error(err);process.exitCode=1});
"""


def _answer(ident, state, *, tps=None, error=None):
    return {"id": ident, "state": state, "text": "Answer", "tps": tps,
            "error": error, "model": "Nemotron Mini 4B"}


def _model(pane, kind, answer, *, live_speed=None):
    return {"pane": pane, "kind": kind, "label": "Nemotron Mini 4B", "model": "Nemotron Mini 4B",
            "maker": "NVIDIA", "where": "on this phone" if kind == "phone" else "on the PC's GPU",
            "ready": True, "answer": answer, "live_speed": live_speed}


@unittest.skipIf(shutil.which("node") is None, "needs node to run the page script")
class PageStatusTest(NoNetwork):
    def run_page(self, snapshot, reply=None, *, during_request=None, after=None, after_action=None,
                 search=""):
        script = _constants(PAGE, "_SCRIPT")[0][1]
        done = subprocess.run(["node", "-e", NODE_HARNESS],
                              input=json.dumps({"script": script, "snapshot": snapshot, "reply": reply,
                                                "duringRequest": during_request, "after": after,
                                                "afterAction": after_action, "search": search}),
                              capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_one_live_region_announces_completion_once_without_reading_live_speeds(self):
        markup = _constants(PAGE, "_LIST")[0][1] + _constants(PAGE, "_THUMB")[0][1]
        script = _constants(PAGE, "_SCRIPT")[0][1]
        self.assertEqual(markup.count('role="status"'), 1)
        self.assertNotIn("setAttribute('role','status')", script)

        snap = _snapshot()
        snap["models"] = [_model("m1", "phone", _answer("m", "answering"), live_speed=7)]
        changed_speed = json.loads(json.dumps(snap))
        changed_speed["rev"] = 2
        changed_speed["models"][0]["live_speed"] = 12
        done = json.loads(json.dumps(changed_speed))
        done["rev"] = 3
        done["models"][0]["answer"]["state"] = "done"
        shown = self.run_page(snap, after=changed_speed,
                              after_action=f"draw({json.dumps(done)});draw({json.dumps(done)})")
        self.assertEqual(shown["statusWrites"], ["Nemotron Mini 4B: Done"])
        self.assertEqual(shown["announcement"], "Nemotron Mini 4B: Done")

    def test_stopped_and_failed_answers_are_announced_once(self):
        for state, error, expected in (("cancelled", None, "Stopped"),
                                       ("failed", "stream_error", "The phone model could not finish the answer.")):
            with self.subTest(state=state):
                snap = _snapshot()
                snap["models"] = [_model("m1", "phone", _answer("m", "answering"), live_speed=7)]
                finished = json.loads(json.dumps(snap))
                finished["rev"] = 2
                finished["models"][0]["answer"].update(state=state, error=error)
                shown = self.run_page(snap, after=finished,
                                      after_action=f"draw({json.dumps(finished)})")
                self.assertEqual(shown["statusWrites"], [f"Nemotron Mini 4B: {expected}"])

    def test_cable_loss_announces_once_until_the_connection_recovers(self):
        snap = _snapshot({"label": "M5 Pro MacBook Pro", "live": True, "state": "idle"})
        snap["gpu"]["answer"] = _answer("g", "answering")
        disconnected = json.loads(json.dumps(snap))
        disconnected["rev"] = 2
        disconnected["gpu"]["link"]["pc"]["live"] = False
        reconnected = json.loads(json.dumps(snap))
        reconnected["rev"] = 3
        disconnected_again = json.loads(json.dumps(disconnected))
        disconnected_again["rev"] = 4
        shown = self.run_page(snap, after=disconnected,
                              after_action=";".join(f"draw({json.dumps(s)})" for s in
                                                    (disconnected, reconnected,
                                                     disconnected_again, disconnected_again)))
        warning = "Not connected. The answer is saved and continues when the MacBook is ready again."
        recovery = "Connected. Safe to unplug: the answer is saved and continues when the MacBook is ready again."
        self.assertEqual(shown["statusWrites"], [warning, recovery, warning])

    def test_storage_warnings_announce_once_for_a_fault_or_startup_notice(self):
        cases = (
            ({"label": "M5 Pro MacBook Pro", "live": True, "state": "idle"}, True, "",
             "The phone could not save the answer. Wait before unplugging."),
            (None, False, "A saved answer was damaged and moved aside. Restart AI mode to continue.",
             "A saved answer was damaged and moved aside. Restart AI mode to continue."),
        )
        for pc, fault, message, expected in cases:
            with self.subTest(storage_fault=fault):
                snap = _snapshot(pc)
                snap["gpu"]["link"].update(storage=None, storage_fault=False, storage_notice="")
                warning = json.loads(json.dumps(snap))
                warning["rev"] = 2
                warning["gpu"]["link"].update(storage="error", storage_fault=fault,
                                               storage_notice=message)
                shown = self.run_page(snap, after=warning,
                                      after_action=f"draw({json.dumps(warning)})")
                self.assertEqual(shown["statusWrites"], [expected])

    def test_cable_loss_is_announced_while_a_storage_notice_remains(self):
        snap = _snapshot({"label": "M5 Pro MacBook Pro", "live": True, "state": "idle"})
        snap["gpu"]["answer"] = _answer("g", "answering")
        notice = "A saved answer was damaged and moved aside. Restart AI mode to continue."
        snap["gpu"]["link"].update(storage="error", storage_fault=False, storage_notice=notice)
        disconnected = json.loads(json.dumps(snap))
        disconnected["rev"] = 2
        disconnected["gpu"]["link"]["pc"]["live"] = False
        shown = self.run_page(snap, after=disconnected,
                              after_action=f"draw({json.dumps(disconnected)})")
        cable = "Not connected. The answer is saved and continues when the MacBook is ready again."
        self.assertEqual(shown["statusWrites"], [notice, notice + " " + cable])

    def test_saved_macbook_answer_uses_its_own_computer_in_the_announcement(self):
        snap = _snapshot({"label": "M5 Pro MacBook Pro", "live": True, "state": "idle"})
        snap["gpu"]["answer"] = _answer("g", "answering")
        snap["gpu"]["answer"].update(model="Nemotron 3.5 Bolt", where="M5 Pro MacBook Pro")
        finished = json.loads(json.dumps(snap))
        finished["rev"] = 2
        finished["gpu"]["link"]["pc"]["label"] = "RTX 5080 PC"
        finished["gpu"]["answer"]["state"] = "done"
        shown = self.run_page(snap, after=finished,
                              after_action=f"draw({json.dumps(finished)})")
        self.assertEqual(shown["statusWrites"], ["MacBook GPU: Done"])

    def test_two_fast_answers_with_the_same_done_words_both_announce(self):
        first = _snapshot()
        first["models"] = [_model("m1", "phone", _answer("first", "done"))]
        second = json.loads(json.dumps(first))
        second["rev"] = 2
        second["models"][0]["answer"]["id"] = "second"
        shown = self.run_page(first, after=second)
        self.assertEqual(shown["statusWrites"], ["Nemotron Mini 4B: Done", "",
                                                 "Nemotron Mini 4B: Done"])

    def test_single_pane_does_not_announce_an_answer_hidden_on_the_other_pane(self):
        for visible, hidden in (("phone", "gpu"), ("gpu", "phone")):
            with self.subTest(visible=visible):
                snap = _snapshot()
                snap[hidden]["answer"] = _answer("hidden", "done")
                shown = self.run_page(snap, search="?pane=" + visible)
                self.assertEqual(shown["statusWrites"], [])

    def test_live_speed_names_the_measured_unit_and_this_run(self):
        snap = _snapshot()
        snap["phone"]["answer"] = _answer("p", "answering")
        snap["phone"]["live_speed"] = 4
        snap["models"] = [_model("m1", "phone", _answer("m", "answering"), live_speed=7),
                          _model("g1", "pc", _answer("g", "answering"), live_speed=6)]
        shown = self.run_page(snap)
        self.assertEqual(shown["phoneSpeed"], "about 4 pieces per second · this run")
        self.assertEqual(shown["m1Speed"], "about 7 pieces per second · this run")
        self.assertEqual(shown["g1Speed"], "about 6 tokens per second · this run")

    def test_finished_speed_is_labelled_as_one_run(self):
        snap = _snapshot()
        snap["phone"]["answer"] = _answer("p", "done", tps=12)
        snap["models"] = [_model("m1", "phone", _answer("m", "done", tps=8))]
        shown = self.run_page(snap)
        self.assertEqual(shown["phoneSpeed"], "12 tokens per second · this run")
        self.assertEqual(shown["m1Speed"], "8 tokens per second · this run")
        self.assertEqual(shown["m1State"], "Done")

    def test_phone_cards_use_the_same_specific_failure_words(self):
        for code, words in (("low_memory", "Not enough free memory for this model right now."),
                            ("model_start", "This model could not start."),
                            ("unknown", "The phone could not finish the answer.")):
            with self.subTest(code=code):
                snap = _snapshot()
                snap["phone"]["answer"] = _answer("p", "failed", error=code)
                snap["models"] = [_model("m1", "phone", _answer("m", "failed", error=code))]
                shown = self.run_page(snap)
                self.assertEqual(shown["phoneSpeed"], words)
                self.assertEqual(shown["m1Speed"], words)

    def test_waiting_and_loading_words_match_the_main_cards(self):
        snap = _snapshot()
        snap["phone"]["answer"] = _answer("p", "waiting")
        snap["gpu"]["answer"] = _answer("g", "loading")
        snap["models"] = [_model("m1", "phone", _answer("m", "waiting")),
                          _model("g1", "pc", _answer("g1", "loading"))]
        shown = self.run_page(snap)
        self.assertEqual(shown["m1Speed"], shown["phoneSpeed"])
        self.assertEqual(shown["m1Speed"], "Waiting for the phone model")
        self.assertEqual(shown["g1Speed"], shown["gpuSpeed"])
        self.assertEqual(shown["g1Speed"], "Loading the model")

    def test_locked_response_does_not_show_a_raw_error(self):
        snap = _snapshot()
        shown = self.run_page(snap, {"status": 403, "body": {"error": "locked"}})
        self.assertTrue(shown["controlsHidden"])
        self.assertEqual(shown["phoneSpeed"], "Unlock the phone to use AI mode.")
        self.assertEqual(shown["gpuSpeed"], "Unlock the phone to use AI mode.")
        self.assertEqual(shown["error"], "")
        self.assertEqual(shown["announcement"], "Unlock the phone to use AI mode.")

    def test_locked_response_discards_queued_ask_and_ask_works_after_unlock(self):
        snap = _snapshot()
        snap["models"] = [_model("m1", "phone", None), _model("g1", "pc", None)]
        shown = self.run_page(snap, {"status": 403, "body": {"error": "locked"}},
                              during_request="G('ask').onclick()", after=snap,
                              after_action="G('ask').onclick()")
        self.assertEqual(shown["responseState"],
                         {"askQueued": False, "queued": 0, "controlsHidden": True,
                          "phoneRootHidden": True, "pcRootHidden": True})
        self.assertFalse(shown["controlsHidden"])
        self.assertTrue(shown["askQueued"])
        self.assertEqual(shown["queued"], 1)

    def test_forbidden_response_disables_ask_and_discards_queued_ask(self):
        snap = _snapshot()
        shown = self.run_page(snap, {"status": 403, "body": {"error": "forbidden"}},
                              during_request="G('ask').onclick()", after_action="G('ask').onclick()")
        self.assertTrue(shown["askDisabled"])
        self.assertFalse(shown["askQueued"])
        self.assertEqual(shown["queued"], 0)
        self.assertEqual(shown["error"], "This page is out of date. Reload it, then try again.")
        self.assertEqual(shown["announcement"], shown["error"])


if __name__ == "__main__":
    unittest.main()

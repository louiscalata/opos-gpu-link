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
class El{
 constructor(id){this.id=id;this.text='';this.hidden=false;this.dataset={};this.attrs={};
  this.children=[];this.value='';this.style={};this.scrollHeight=0;this.clientHeight=0;
  this.scrollTop=0;this.classList={toggle(){},add(){},remove(){}}}
 set textContent(v){this.text=String(v);this.children=[];
  if(this.id.endsWith('-announcement'))statusWrites.push([this.id,this.text])}
 get textContent(){return this.text}
 appendChild(c){this.children.push(c);c.parentNode=this;return c} insertBefore(c){return this.appendChild(c)}
 setAttribute(k,v){this.attrs[k]=String(v)} getAttribute(k){return this.attrs[k]}
 remove(){} focus(){} addEventListener(){}
}
const get=id=>{if(!nodes.has(id))nodes.set(id,new El(id));return nodes.get(id)};
const document={hidden:false,documentElement:new El('html'),getElementById:get,
 createElement:()=>new El(''),activeElement:null,
 querySelector:()=>({content:'fixture-token'}),addEventListener(){}};
const refuse=name=>function(){throw new Error(name+' is not allowed in tests')};
const ctx=vm.createContext({document,location:{search:''},URLSearchParams,AbortController,
 WebSocket:refuse('WebSocket'),EventSource:refuse('EventSource'),XMLHttpRequest:refuse('XMLHttpRequest'),
 performance:{now:()=>0},setTimeout:()=>0,clearTimeout(){},console,
 fetch:()=>{if(input.duringRequest)vm.runInContext(input.duringRequest,ctx);
  return input.reply?Promise.resolve({status:input.reply.status,
   json:()=>Promise.resolve(input.reply.body)}):new Promise(()=>{})}});
(async()=>{
 vm.runInContext(input.script,ctx);
 vm.runInContext('draw('+JSON.stringify(input.snapshot)+')',ctx);
 const initialWrites=statusWrites.slice();
 if(input.reply){vm.runInContext('request()',ctx);await new Promise(setImmediate)}
 const responseState={askQueued:vm.runInContext('askQueued',ctx),
  queued:vm.runInContext('queue.length',ctx),controlsHidden:get('controls').hidden,
  phoneRootHidden:get('phone-extra').hidden,pcRootHidden:get('pc-extra').hidden};
 if(input.after)vm.runInContext('draw('+JSON.stringify(input.after)+')',ctx);
 const pollWrites=[];
 for(const snapshot of input.polls||[]){
  const before=statusWrites.length;
  vm.runInContext('draw('+JSON.stringify(snapshot)+')',ctx);
  pollWrites.push(statusWrites.slice(before));
 }
 if(input.afterAction)vm.runInContext(input.afterAction,ctx);
 process.stdout.write(JSON.stringify({phoneSpeed:get('phone-speed').text,
  gpuSpeed:get('gpu-speed').text,m1Speed:get('m1-speed').text,g1Speed:get('g1-speed').text,
  gpuCable:get('gpu-cable').text,initialWrites,pollWrites,
  phoneState:get('phone-state').text,m1State:get('m1-state').text,g1State:get('g1-state').text,
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
    def run_page(self, snapshot, reply=None, *, during_request=None, after=None, polls=None,
                 after_action=None):
        script = _constants(PAGE, "_SCRIPT")[0][1]
        done = subprocess.run(["node", "-e", NODE_HARNESS],
                              input=json.dumps({"script": script, "snapshot": snapshot, "reply": reply,
                                                "duringRequest": during_request, "after": after,
                                                "polls": polls, "afterAction": after_action}),
                              capture_output=True, text=True, timeout=30, check=False)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_main_speed_and_cable_are_not_live_but_status_regions_are(self):
        markup = _constants(PAGE, "_LIST")[0][1] + _constants(PAGE, "_THUMB")[0][1]
        for ident in ("phone", "gpu"):
            with self.subTest(ident=ident):
                self.assertRegex(markup, rf'<p id="{ident}-speed"[^>]* aria-live="off"')
                self.assertRegex(markup, rf'<p id="{ident}-announcement"[^>]* role="status"')
        self.assertRegex(markup, r'<p id="gpu-cable" hidden>')
        self.assertRegex(markup, r'<p id="gpu-cable-announcement"[^>]* role="status"')

    def test_speed_and_word_ticks_do_not_write_to_status_regions(self):
        snap = _snapshot()
        snap["phone"]["answer"] = _answer("p", "answering")
        snap["phone"]["live_speed"] = 4
        snap["models"] = [_model("m1", "phone", _answer("m", "answering"), live_speed=7),
                          _model("g1", "pc", _answer("g", "answering"), live_speed=6)]
        polls = []
        for rev, speed in ((2, 8), (3, 9), (4, 10)):
            later = json.loads(json.dumps(snap))
            later["rev"] = rev
            later["phone"]["live_speed"] = speed
            later["phone"]["answer"]["tokens"] = rev
            later["models"][0]["live_speed"] = speed + 1
            later["models"][0]["answer"]["tokens"] = rev
            later["models"][1]["live_speed"] = speed + 2
            later["models"][1]["answer"]["tokens"] = rev
            polls.append(later)
        shown = self.run_page(snap, polls=polls)
        self.assertEqual(shown["pollWrites"], [[], [], []])
        self.assertEqual(shown["phoneSpeed"], "about 10 pieces per second · this run")
        self.assertEqual(shown["m1Speed"], "about 11 pieces per second · this run")
        self.assertEqual(shown["g1Speed"], "about 12 tokens per second · this run")

    def test_every_extra_model_transition_is_announced_once(self):
        snap = _snapshot()
        snap["models"] = [_model("m1", "phone", None)]
        states = [("a1", "queued", None), ("a1", "queued", None),
                  ("a1", "answering", None), ("a1", "answering", None),
                  ("a1", "done", None), ("a1", "done", None),
                  ("a2", "queued", None), ("a2", "cancelled", None),
                  ("a3", "queued", None), ("a3", "failed", "model_start"),
                  ("a3", "failed", "model_start"), (None, None, None)]
        polls = []
        for rev, (ident, state, error) in enumerate(states, 2):
            later = json.loads(json.dumps(snap))
            later["rev"] = rev
            later["models"][0]["answer"] = _answer(ident, state, error=error) if ident else None
            if state == "answering":
                later["models"][0]["live_speed"] = rev
                later["models"][0]["answer"]["tokens"] = rev
            if state == "done":
                later["models"][0]["answer"]["tps"] = rev
            polls.append(later)
        shown = self.run_page(snap, polls=polls)
        self.assertEqual([w for w in shown["initialWrites"] if w[0] == "m1-announcement"],
                         [["m1-announcement", "Nemotron Mini 4B: Ready"]])
        self.assertEqual([[w[1] for w in writes if w[0] == "m1-announcement"]
                          for writes in shown["pollWrites"]], [
                              ["Nemotron Mini 4B: Queued behind an earlier answer"], [],
                              ["Nemotron Mini 4B: Answering"], [],
                              ["Nemotron Mini 4B: Done"], [],
                              ["Nemotron Mini 4B: Queued behind an earlier answer"],
                              ["Nemotron Mini 4B: Stopped"],
                              ["Nemotron Mini 4B: Queued behind an earlier answer"],
                              ["Nemotron Mini 4B: This model could not start."], [],
                              ["Nemotron Mini 4B: Ready"]])
        self.assertEqual(shown["m1Speed"], "Ready")

    def test_primary_phone_transitions_are_announced_once(self):
        snap = _snapshot()
        snap["phone"]["ready"] = True
        states = [("p1", "queued", None), ("p1", "answering", None),
                  ("p1", "answering", None), ("p1", "done", None),
                  ("p1", "done", None), ("p2", "failed", "worker_start"),
                  ("p2", "failed", "worker_start"), (None, None, None)]
        polls = []
        for rev, (ident, state, error) in enumerate(states, 2):
            later = json.loads(json.dumps(snap))
            later["rev"] = rev
            later["phone"]["answer"] = _answer(ident, state, error=error) if ident else None
            if state == "answering":
                later["phone"]["live_speed"] = rev
            if state == "done":
                later["phone"]["answer"]["tps"] = rev
            polls.append(later)
        shown = self.run_page(snap, polls=polls)
        self.assertEqual([[w[1] for w in writes if w[0] == "phone-announcement"]
                          for writes in shown["pollWrites"]], [
                              ["Phone: Queued behind an earlier answer"], ["Phone: Answering"], [],
                              ["Phone: Done"], [], ["Phone: The phone could not start the answer."],
                              [], ["Phone: Ready"]])

    def test_copy_progress_is_quiet_and_cable_and_storage_changes_are_announced(self):
        pc = {"label": "M5 Pro MacBook Pro", "live": True, "state": "ready"}
        snap = _snapshot(pc)
        snap["gpu"]["link"]["model"] = {"state": "ready"}
        polls = []
        disconnected = json.loads(json.dumps(snap))
        disconnected["rev"] = 2
        disconnected["gpu"]["link"]["pc"]["live"] = False
        polls.append(disconnected)
        reconnect = json.loads(json.dumps(snap))
        reconnect["rev"] = 3
        polls.append(reconnect)
        warning = json.loads(json.dumps(reconnect))
        warning["rev"] = 4
        warning["gpu"]["link"].update(storage="error",
                                      storage_notice="A saved answer was damaged and moved aside.")
        polls.append(warning)
        same_warning = json.loads(json.dumps(warning))
        same_warning["rev"] = 5
        polls.append(same_warning)
        fault = json.loads(json.dumps(warning))
        fault["rev"] = 6
        fault["gpu"]["link"]["storage_fault"] = True
        polls.append(fault)
        recovered = json.loads(json.dumps(reconnect))
        recovered["rev"] = 7
        polls.append(recovered)
        shown = self.run_page(snap, polls=polls)
        self.assertEqual([[w[1] for w in writes if w[0] == "gpu-announcement"]
                          for writes in shown["pollWrites"]], [
                              ["MacBook GPU: Waiting for the MacBook"], ["MacBook GPU: Ready"],
                              ["MacBook GPU: A saved answer was damaged and moved aside."], [], [],
                              ["MacBook GPU: Ready"]])
        self.assertEqual([[w[1] for w in writes if w[0] == "gpu-cable-announcement"]
                          for writes in shown["pollWrites"]], [
                              ["Not connected. Check the cable and the MacBook."],
                              ["Connected. Safe to unplug."], [], [],
                              ["A saved answer was damaged and moved aside. Wait before unplugging."],
                              ["Connected. Safe to unplug."]])

        copying = json.loads(json.dumps(snap))
        copying["gpu"]["link"]["pc"].update(state="copying", total=100, copied=10)
        later = json.loads(json.dumps(copying))
        later["rev"] = 2
        later["gpu"]["link"]["pc"]["copied"] = 80
        shown = self.run_page(copying, polls=[later])
        self.assertIn("80%", shown["gpuSpeed"])
        self.assertEqual(shown["pollWrites"], [[]])

    def test_cable_announcement_matches_visible_text_for_link_and_storage_states(self):
        cases = (
            (False, True, "The phone could not save the answer."),
            (True, True, "The phone could not save the answer. Wait before unplugging."),
            (False, False, "Not connected. Check the cable and the MacBook."),
            (True, False, "Connected. Safe to unplug."),
        )
        for live, fault, expected in cases:
            with self.subTest(live=live, storage_fault=fault):
                snap = _snapshot({"label": "M5 Pro MacBook Pro", "live": live, "state": "ready"})
                snap["gpu"]["link"]["model"] = {"state": "ready"}
                snap["gpu"]["link"]["storage_fault"] = fault
                snap["gpu"]["link"]["storage"] = "error" if fault else None
                shown = self.run_page(snap)
                announced = [words for ident, words in shown["initialWrites"]
                             if ident == "gpu-cable-announcement"]
                self.assertEqual(shown["gpuCable"], expected)
                self.assertEqual(announced, [shown["gpuCable"]])

    def test_answer_start_announces_changed_cable_words_without_link_change(self):
        snap = _snapshot({"label": "M5 Pro MacBook Pro", "live": True, "state": "ready"})
        snap["gpu"]["link"]["model"] = {"state": "ready"}
        answering = json.loads(json.dumps(snap))
        answering["rev"] = 2
        answering["gpu"]["answer"] = _answer("g", "answering")
        repeated = json.loads(json.dumps(answering))
        repeated["rev"] = 3
        shown = self.run_page(snap, polls=[answering, repeated])
        self.assertEqual(shown["gpuCable"],
                         "Connected. Safe to unplug: the answer is saved and continues when the MacBook is ready again.")
        self.assertEqual([[words for ident, words in writes if ident == "gpu-cable-announcement"]
                          for writes in shown["pollWrites"]], [[shown["gpuCable"]], []])

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


if __name__ == "__main__":
    unittest.main()

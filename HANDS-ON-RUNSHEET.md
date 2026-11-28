# Hands-on demo runsheet

Galaxy Z Flip6, USB-C data cable, Apple-silicon MacBook, desktop companion. Complete these checks in one sitting. Start the phone service and companion using the [quick start](README.md#quick-start). Keep the companion running through cable pulls.

In a second Mac terminal, set `ADB` to the exact adb executable the companion uses, for example `ADB=/absolute/path/to/adb`. Use `ADB=$(command -v adb)` only if it finds that same executable. Check with `"$ADB" version`. Run `"$ADB" devices -l` and confirm one authorized phone. A mismatched adb can restart the server. Repeat this setup on a second computer. Leave the ADB server and app data alone.

Write local clock times. Mark each row **PASS**, **FAIL**, or **NOT_RUN** only after observing it. Add a short reason for a failure or an unavailable lane. The stand-alone phone service does not provide the planned `m1` and `m4` pool. Those checks need the full OPOS phone host with ready local models.

## 1. Flip screens and new-computer prompt

**Goal:** Check inner Main, Info, and Settings; closed cover Main; and a new-computer pairing prompt on the cover.

**Preconditions:** Phone unfolded, unlocked, cool; cable connected; app and companion running. A new-computer prompt needs a computer this phone has not paired with. If none is available, mark that row NOT_RUN. Do not remove a saved pairing to create a prompt.

**Steps:**

1. On the inner screen, inspect Main and scroll through the cards. Tap **Info**, inspect its rows, then close it. Tap **Settings**, inspect its rows, then close it.
2. Fold closed and wake the cover. Inspect Main, its cards, and controls. Unfold.
3. If available, connect a genuinely unpaired computer with authorized ADB while the phone is unfolded. Start its companion from the quick start. USB debugging approval is separate from GPU Link pairing. Trigger the GPU Link pairing request while unfolded. Take the section 8 inner shot from this computer. Fold closed while the prompt is live. Check that the title, computer name, code, **Allow**, and **Not now** fit. Take the section 8 cover shot. Compare codes before any **Allow** tap. If this was a second computer, tap **Not now** and return to the demo MacBook. If this was the first pairing for the demo MacBook, tap **Allow** only after the codes match.

**PASS:** Text and controls are readable, reachable, and not clipped. Info and Settings open and close. The new-computer prompt fits on the cover and matches the companion's code.

| Check | Time | Result | Note |
| --- | --- | --- | --- |
| Inner Main | ____ | ____ | ____ |
| Info | ____ | ____ | ____ |
| Settings | ____ | ____ | ____ |
| Closed cover Main | ____ | ____ | ____ |
| New-computer cover prompt | ____ | ____ | ____ |

## 2. Live Stop re-check

**Goal:** Confirm Stop ends a streaming MacBook answer and a waiting phone pool answer.

**Preconditions:** Phone unfolded, unlocked, cool; cable connected; MacBook lane ready. For the pool trial, a phone pool card must visibly enter a waiting state. Use separate asks because Stop acts on all open lanes.

**Steps:**

1. Ask a prompt long enough to show live MacBook text. While text arrives, tap **Stop**. Watch the card until it settles.
2. Start a new ask with the phone pool ready. While a pool card is still waiting, tap **Stop**. Watch for any late start.

**PASS:** The MacBook stream stops without more text arriving. The waiting pool card never starts after Stop. Neither card stays stuck running.

| Check | Time of Stop | Result | Last observed state |
| --- | --- | --- | --- |
| MacBook mid-stream | ____ | ____ | ____ |
| Phone pool waiting | ____ | ____ | ____ |

## 3. Ask during pause; pull and replug mid-answer

**Goal:** Check an ask while the cable is out, then recovery of a partly shown MacBook answer.

**Preconditions:** Phone unfolded, unlocked, cool; cable connected; companion running. Keep its MacBook terminal open during both pulls.

**Steps:**

1. With no answer running, pull the cable. Wait for the computer lane to show paused or unavailable. Ask on the phone. Note whether the ask is accepted and any ready phone lane continues. Replug and wait for the computer lane to recover.
2. With the cable connected, start a new ask. Once MacBook text appears, write down its last visible complete word. Pull the cable physically. Wait for the pause state and confirm the shown prefix stays on screen.
3. Replug without restarting the companion. Compare the resumed answer with that saved prefix.

**PASS:** The phone accepts the ask during the pause. The computer lane recovers after replug. The mid-answer prefix is unchanged, and new text follows the same last word without a duplicate or gap. Later wording may differ from an uninterrupted answer.

| Check | Pull / replug / resume times | Result | Last word / note |
| --- | --- | --- | --- |
| Ask while cable out | ____ / ____ / ____ | ____ | ____ |
| Pull mid-answer | ____ / ____ / ____ | ____ | ____ |

## 4. Forget tap-through without forgetting

**Goal:** Check both Info confirmation dialogs while keeping the saved computer.

**Preconditions:** Phone unfolded, unlocked, cool; cable connected; saved MacBook pairing visible in Info; no answer running.

**Steps:**

1. Open **Info** and note the displayed computer name and connection state.
2. Tap **Forget this PC** (or the button with that computer's name). On the first dialog, tap **Continue**.
3. Inspect the second dialog. Tap **Not now**. Do not tap **Forget PC**. Recheck the name and connection state in Info.

**PASS:** The second confirmation appears, **Not now** exits it, and the same saved MacBook remains connected.

| Check | Time | Result | Computer state after exit |
| --- | --- | --- | --- |
| Two-dialog tap-through | ____ | ____ | ____ |

## 5. Timed 1 GB idle cable copy

**Goal:** Time a standard ADB push and pull of one generated 1,000,000,000-byte file.

**Preconditions:** Phone unfolded, unlocked, cool; cable connected; no answer running; one authorized phone in `"$ADB" devices -l`. Have room for the file on the phone and two copies on the MacBook. Use a second terminal.

**Steps:** Run each command in the same terminal. Check each result before the next. The `real` values are elapsed transfer times. If a transfer fails, record FAIL and still clean up the named test files.

```sh
COPY_DIR=$(mktemp -d)
dd if=/dev/urandom of="$COPY_DIR/opos-copy-1gb.bin" bs=1000000 count=1000
wc -c < "$COPY_DIR/opos-copy-1gb.bin"
/usr/bin/time -p "$ADB" push "$COPY_DIR/opos-copy-1gb.bin" /sdcard/Download/opos-copy-1gb.bin
/usr/bin/time -p "$ADB" pull /sdcard/Download/opos-copy-1gb.bin "$COPY_DIR/opos-copy-returned.bin"
cmp "$COPY_DIR/opos-copy-1gb.bin" "$COPY_DIR/opos-copy-returned.bin" && echo MATCH
"$ADB" shell rm -f /sdcard/Download/opos-copy-1gb.bin
rm -f "$COPY_DIR/opos-copy-1gb.bin" "$COPY_DIR/opos-copy-returned.bin"
rmdir "$COPY_DIR"
```

**PASS:** `wc -c` prints 1000000000, both transfers complete, the comparison prints MATCH, and the test files are removed. Record measured times; there is no preset speed target.

| Check | Clock time | Result | `real` seconds / note |
| --- | --- | --- | --- |
| Push | ____ | ____ | ____ |
| Pull | ____ | ____ | ____ |
| Compare and cleanup | ____ | ____ | ____ |

## 6. Thirty-minute live soak

**Goal:** Run repeated live asks for 30 minutes while watching phone thermal status.

**Preconditions:** Phone unfolded, unlocked, cool; cable connected; companion and intended phone lanes ready. Start idle. The [pacing note](tools/README.md) describes a simulator, not a completed live soak.

**Steps:**

1. Run `"$ADB" shell dumpsys thermalservice` and read **Thermal Status**. Android's scale is 0 none, 1 light, 2 moderate, 3 severe, 4 critical, 5 emergency, and 6 shutdown. Start a 30-minute timer.
2. Ask a short demo question and wait for all selected cards to finish. This runsheet's chosen profile uses a 30-second gap before the next ask. After every second completed ask, use a 120-second cool-down instead. Check thermal status before each ask and during gaps with the same read-only command. Note any status of 3.
3. If Thermal Status reaches **4 or higher**, tap **Stop**, end the soak, and record the time and status. Otherwise continue until 30 minutes. Note completed asks, card failures, and any restart.

**PASS:** The full 30 minutes finish with the intended lanes responding, no stuck cards or forced restarts, and every observed Thermal Status below 4. An early thermal stop is recorded, not a pass.

| Check | Time | Result | Thermal Status / asks / note |
| --- | --- | --- | --- |
| Start | ____ | ____ | ____ |
| Ask #____ (copy row as needed) | ____ | ____ | ____ |
| End or thermal stop | ____ | ____ | ____ |

## 7. Two dress rehearsals and backup recording

**Goal:** Fit the live sequence into the five-minute slot twice, then save a phone screen video backup.

**Preconditions:** Phone unfolded, unlocked, cool; cable connected; companion and intended lanes ready. Keep a separate ADB terminal open. Let the phone cool before each run.

**Steps:**

1. Start a five-minute timer at the first audience-facing action. On Main, ask the prepared demo prompt, show live cards, tap **Stop**, show Info and Settings, then fold to show the cover. End the timer at the last action. Record elapsed time and any stall.
2. Return to idle and repeat the same sequence and timing once more.
3. Run a backup pass while recording the inner sequence. `screenrecord` records one display. Each file is limited to three minutes. Start the second clip as soon as the first command ends. Pull both files to the MacBook and play them. Finish the inner recording before folding. Record a separate cover clip with `--display-id <cover_id>`, or film the fold externally.

```sh
"$ADB" shell screenrecord --time-limit 180 /sdcard/Download/opos-backup-1.mp4
"$ADB" shell screenrecord --time-limit 180 /sdcard/Download/opos-backup-2.mp4
"$ADB" pull /sdcard/Download/opos-backup-1.mp4 .
"$ADB" pull /sdcard/Download/opos-backup-2.mp4 .
```

For a cover clip, fold closed and use the cover ID from section 8. If `screenrecord` refuses `--display-id` or the clip shows the inner screen, film the fold externally instead. Replace `<cover_id>` before running these commands. List display IDs as in section 8 if needed.

```sh
"$ADB" shell screenrecord --display-id <cover_id> --time-limit 180 /sdcard/Download/opos-backup-cover.mp4
"$ADB" pull /sdcard/Download/opos-backup-cover.mp4 .
```

After playback, delete only the named phone files you made. If you made a cover clip, delete that phone file too.

```sh
"$ADB" shell rm -f /sdcard/Download/opos-backup-1.mp4 /sdcard/Download/opos-backup-2.mp4
"$ADB" shell rm -f /sdcard/Download/opos-backup-cover.mp4
```

**PASS:** Both rehearsals end within five minutes. Every demo action works, with no stall, dropped lane, or crash. Both inner clips play, and the separate cover clip or external film shows the fold. Note any gap between clips.

| Check | Start / end times | Result | Elapsed / file / note |
| --- | --- | --- | --- |
| Rehearsal 1 | ____ / ____ | ____ | ____ |
| Rehearsal 2 | ____ / ____ | ____ | ____ |
| Backup clips | ____ / ____ | ____ | ____ |

## 8. Pairing-dialog screenshots

**Goal:** Keep legible inner and cover screenshots of a real new-computer pairing dialog.

**Preconditions:** Phone unfolded, unlocked, cool; cable connected to a genuinely unpaired computer with authorized ADB; its companion running. Set `ADB` to the executable used by this companion. If the prompt appeared in section 1, take these shots then, before it expires, and inspect them here. Otherwise use a new prompt only if one is available.

**Steps:**

1. Run `"$ADB" shell dumpsys SurfaceFlinger --display-id` to list display IDs without changing the phone. Identify the inner and cover IDs. The Flip6 cover is a separate display. Replace `<inner_id>` and `<cover_id>` below with those IDs. If the cover ID is absent while unfolded, list IDs again after folding. `screencap -d` takes these SurfaceFlinger IDs, not the small logical IDs from `dumpsys display`. If the command lists nothing, mark the cover shot NOT_RUN rather than guessing an ID.
2. With the pairing dialog open on the inner screen, run `"$ADB" exec-out screencap -d <inner_id> -p > pairing-inner.png` in this computer's ADB terminal.
3. Fold closed while the prompt is live. Check the cover fit. Run `"$ADB" exec-out screencap -d <cover_id> -p > pairing-cover.png`.
4. Open both PNGs. Check that each shows the intended display, computer name, code, **Allow**, and **Not now** without clipping. Record filenames and times. If a prompt is unavailable, mark the missing shot NOT_RUN.

**PASS:** Both saved PNGs open and clearly show the real pairing dialog on the intended display.

| Check | Time | Result | Filename / note |
| --- | --- | --- | --- |
| Inner prompt | ____ | ____ | ____ |
| Cover prompt | ____ | ____ | ____ |

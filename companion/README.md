# Computer companion

This per-user companion watches one authorized adb phone, creates a checked loopback forward on this computer to phone port 8767, performs first pairing with the phone's six-digit compare/Allow flow, and runs the existing signed GPU Link worker. A saved phone key is reused on replug; rejection stops without automatic re-enrolment. The local model server and model must already be running. Before reporting ready for requests, the companion sends a one-token streaming request to the exact `--server` route with the exact `--model`. A valid choice finish (`stop` or `length`) followed by `[DONE]` passes even if the one-token answer has no text. That preflight checks the route and stream, but does not prove GPU hardware execution or continuation after a cable loss.

## Setup

See the [cross-platform setup guide](SETUP.md) for the macOS, Windows and Linux launchers,
USB debugging, backend discovery, model sizing and troubleshooting.

## Run

Set `OPOS_GPU_LINK_MODEL` to the name at your local chat-completions server, or pass `--model NAME`. Then start one of these commands on the computer (MacBook, Mac or PC):

```sh
OPOS_GPU_LINK_MODEL=YOUR_MODEL ./run-mac.sh
```

```powershell
$env:OPOS_GPU_LINK_MODEL = "YOUR_MODEL"
.\run-windows.ps1
```

The scripts wait and check every two seconds when no authorized phone is present, then select the only authorized USB adb serial automatically. Wireless, IP, emulator, unauthorized, offline, and malformed rows are excluded before counting USB phones. Pass `--serial SERIAL` if more than one valid USB phone is authorized. With no explicit server, startup uses a single discovered backend on an unprotected port and otherwise keeps `http://127.0.0.1:1235/v1/chat/completions`. Use `--lm-url URL` for a backend base URL or `--server URL` for a full chat-completions route. Pass `--adb PATH` if platform tools are not on `PATH`. No port scan, installation, model download, server startup, login item, or firewall change is performed.

The companion says **Warming model** while a cold model prepares its first response. TCP connect has a two-second limit; response headers and first stream event can take up to 90 seconds total, followed by up to 10 seconds for the finish and `[DONE]`. Stop or phone detach cancels that wait. Only one preflight is in flight. A failed check retries after 3, 6, 12, 24, then 30 seconds while the same phone attachment keeps its checked forward and avoids another app launch. Detach or a lost forward begins a new attachment session.

The scripts explicitly opt into `--headless --always-allow`. Headless prints a six-digit compare code for first pairing and waits up to 60 seconds for **Allow** on the phone (the button names this computer, for example **Allow this MacBook**); it never prints the key or question/answer text. On later plugs it uses the saved per-phone key without a prompt on the computer. Starting the process grants use for that process; Ctrl-C or SIGTERM stops the worker and removes its own forward. Without `--always-allow`, a headless grant expires after 120 seconds unplugged and requires a restart. The Tk window remains available by running `python3 -B opos_gpu_link.py --model NAME` without `--headless` when Tk is installed.

The saved key is written only after signed proof of phone Allow. Windows uses current-user DPAPI; macOS and Linux use a user-owned mode-0600 key file. A per-phone lock prevents two companion processes using the same key directory from claiming the same forward. Pairing and grant retention are separate: Stop ends the running grant but does not delete the key. Signed companion requests already carry a stable 16-hex-character, non-secret key fingerprint in `X-Link-Pc`.

For a deliberate computer change, or to show a changed computer label on the phone (for example a Mac now labelled `M5 Pro MacBook Pro` instead of `M5 Pro PC`), first use **Forget** in the phone's GPU Link Info (it names the saved computer, for example **Forget this MacBook**), then stop the old companion. On that computer, run `python3 -B opos_gpu_link.py --reset-pairing --serial SERIAL` from this directory (add its original `--key-dir DIRECTORY` if customized). This command requires the exact USB serial, does not call adb, and removes only that serial's saved key while its companion lock is free. It refuses to run while the companion holds the lock. Then start the companion and compare the new code on the phone. Resetting only the computer's key does not forget phone trust.

The staged phone backend omits the computer's key fingerprint from its `/api/ai` snapshot and accepts `forget` without a fingerprint precondition. Info displays that the fingerprint is unavailable on this phone build; its two confirmations still recheck the saved computer label, and will also compare a fingerprint if a future snapshot supplies `pc.id`. Same-label replacement cannot be guarded atomically until the phone backend includes the ID and checks it during `forget`. This is a backend integration gate, not a verified phone behavior.

## Isolated tests

From the checkout root:

```sh
python3 -B -m unittest discover -s companion -p 'test_*.py' -v
/usr/bin/python3 -B -m unittest discover -s companion -p 'test_*.py' -v
```

The tests use fake adb and do not access the phone. The wire code in `src/opos/gpu_link_proto.py` and `gpu_link_worker.py` is shared with the phone-side link service. Native adb, Windows DPAPI, phone-side pause/resume, and model continuation still need separate checks.

## Runtime answer guard

The companion checks streamed raw text before removing controls. The default-on
guard detects long repeated characters, repeated fragments or word sequences,
wordless symbol/control noise, common encoding junk and answers over 8,192
characters (also bounded by the link's 12,288 UTF-8 bytes). These heuristics reduce
garbage; they cannot establish whether an answer is factually correct.

The stream holds back up to 512 characters while checking new text in slices of
at most 32 characters. This adds display latency, especially for short replies;
a clean completion flushes the held text. A detected suffix is discarded without
retracting any acknowledged prefix. Only that lane's HTTP request closes. The
companion makes one continuation request from its safe prefix with a different
random seed, temperature at most 0.4, top_p 0.9, and repeat_penalty at least 1.1.
An already lower temperature or higher repeat penalty is retained.

A second garble drains the remaining safe prefix as non-final text and sends
the signed status `state="error", error="garbled"`. The app must map that status
to its failed lane and **Garbled — Retry** label. Each lane retains its one-retry
budget across reconnects for the same question lease; a manual retry with a new
lease resets it. Phone-side mapping and new-lease behavior still need device
verification. Set `OPOS_GPU_LINK_GUARD=0` to use the previous streaming behavior.

The pure detector is `gpu_link_guard.py`. Its reason codes are `repeat_char`,
`ngram_loop`, `non_text`, `encoding_junk`, and `runaway_length`; thresholds are
named constants there. It deliberately favors conservative, bounded checks:
unrecognized garbage can pass, and legitimate repetitive or encoding-example
text can be flagged. The test fixtures include normal code, mathematics,
markdown, multilingual prose, and saved RX 580 outputs.

## Show-day guards

These guards reduce garbage and hallucination risk; they do not eliminate either.
`OPOS_GPU_LINK_GUARD=0` disables streamed-garbage checks and their one safer retry.
`OPOS_GPU_LINK_WATCHDOG=0` disables recovery of servers launched by this autosetup process.
`OPOS_GPU_LINK_SYSTEM_PROMPT=0` disables the default concise, grounded `demo_system_prompt.txt` instruction.
Recovery uses only owned server slots; a smaller-model fallback is limited to one swap per lane per show.
Run these from `companion/` with your local paths; review answers and verify real phone/recovery behavior separately.
`python3 -B gpu_link_health.py preflight --offline --backend metal --binary /path/to/llama-server --model-path /path/to/model.gguf --port 38400 --receipt /tmp/gpu-link-preflight.json`
`python3 -B gpu_link_validate.py --own-server --strict-ports --llama-server /path/to/llama-server --model-file /path/to/model.gguf --model preshow-candidate --backend metal --report /tmp/gpu-link-validator.json`

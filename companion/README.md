# OPOS GPU Link computer companion

This companion waits for one authorized USB phone. It pairs with a six-digit code, then signs requests between the phone and computer. A saved pairing is reused after replug; a rejected pairing stops. For the commands below, start a local model server and load a model first.

Before it says it is ready, the companion asks the selected server and model for a one-token streamed answer. A completed stream passes even if it has no text. This checks the server route. It does not prove which GPU ran the model or whether an answer will continue after unplugging.

## Setup

See the [cross-platform setup guide](SETUP.md) for the macOS, Windows and Linux launchers,
USB debugging, finding local model servers, model sizing and troubleshooting.

## Start the companion

Set `OPOS_GPU_LINK_MODEL` to the ID at your local model server, or pass `--model MODEL_ID`. Then start one of these commands on your Mac, Windows computer, or Linux computer:

```sh
OPOS_GPU_LINK_MODEL=MODEL_ID ./run-mac.sh
```

```powershell
$env:OPOS_GPU_LINK_MODEL = "MODEL_ID"
.\run-windows.ps1
```

The scripts wait for an authorized USB phone. They check every two seconds and select it when only one is connected. Network connections, emulators, and unauthorized USB phones are excluded. Wireless: coming later. Pass `--serial SERIAL` if more than one authorized USB phone is connected. With no explicit server, startup uses a local model server it finds only when there is exactly one on an allowed port; otherwise it keeps `http://127.0.0.1:1235/v1/chat/completions`. Use `--lm-url URL` for a server base URL or `--server URL` for a full chat-completions route. Pass `--adb PATH` if platform tools are not on `PATH`. No port scan, installation, model download, server startup, login item, or firewall change is performed.

The companion says **Checking the model.** before the first answer. If a model is still starting when an answer begins, it says **Loading the model.** TCP connect has a two-second limit; response headers and first stream event can take up to 90 seconds total, followed by up to 10 seconds for the finish and `[DONE]`. Stop or phone detach cancels that wait. Only one preflight is in flight. A failed check retries after 3, 6, then every 10 seconds while the same phone attachment keeps its checked forward and avoids another app launch. Detach or a lost forward begins a new attachment session.

The scripts explicitly opt into `--headless --always-allow`. Headless prints a six-digit compare code for first pairing and waits up to 60 seconds for **Allow** on the phone (the button names this computer, for example **Allow this MacBook**); it never prints the key or question/answer text. On later plugs it uses the saved per-phone key without a prompt on the computer. Starting the process grants use for that process; Ctrl-C or SIGTERM stops the worker and removes its own forward. Without `--always-allow`, a headless grant expires after 120 seconds unplugged and requires a restart. The Tk window remains available by running `python3 -B opos_gpu_link.py --model MODEL_ID` without `--headless` when Tk is installed.

The saved key is written only after signed proof of phone Allow. Windows uses current-user DPAPI; macOS and Linux use a user-owned mode-0600 key file. A per-phone lock prevents two companion processes using the same key directory from claiming the same forward. Pairing and grant retention are separate: Stop ends the running grant but does not delete the key. Signed companion requests already carry a stable 16-hex-character, non-secret key fingerprint in `X-Link-Pc`.

For a deliberate computer change, or to correct the computer name shown on the phone, first use **Forget** in the phone's GPU Link Info (for example **Forget this MacBook**). Then stop the old companion. On that computer, run `python3 -B opos_gpu_link.py --reset-pairing --serial SERIAL` from this directory (add its original `--key-dir DIRECTORY` if customized). This command requires the exact USB serial, does not call adb, and removes only that serial's saved key while its companion lock is free. It refuses to run while the companion holds the lock. Then start the companion and compare the new code on the phone. Resetting only the computer's key does not forget phone trust.

The staged phone backend omits the computer's key fingerprint from its `/api/ai` snapshot and accepts `forget` without a fingerprint precondition. Info displays that the fingerprint is unavailable on this phone build; its two confirmations still recheck the saved computer label, and will also compare a fingerprint if a future snapshot supplies `pc.id`. Same-label replacement cannot be guarded atomically until the phone backend includes the ID and checks it during `forget`. This is a backend integration gate, not a verified phone behavior.

## Tests

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

Fluent-looking nonsense (real words, no meaning) passes those checks, so
`gpu_link_salad.py` adds a word-salad judge with reason `word_salad`. It scores
the answer's last 300 characters against its own first 600 with a tiny local
model, and only answers of 1,000 characters or more are judged. It turns on by
itself when both of these are present:
`runtime/salad/SmolLM2-135M-Instruct-Q8_0.gguf` (from
[bartowski/SmolLM2-135M-Instruct-GGUF](https://huggingface.co/bartowski/SmolLM2-135M-Instruct-GGUF),
revision `09816acd`, Apache-2.0; size and sha256
`5a1395716f7913741cc51d98581b9b1228d80987a9f7d3664106742eb06bba83` are checked
once at start) and `llama-perplexity` from the llama.cpp runtime. The judge runs
on the CPU (`OPOS_GPU_LINK_SALAD_NGL=0`), so the answer model keeps the GPU.
`OPOS_GPU_LINK_SALAD=0` turns it off; `OPOS_GPU_LINK_SALAD_BIN` and
`OPOS_GPU_LINK_SALAD_MODEL` override the files, and setting them to an empty
value keeps it off.

## Demo guards

These guards reduce garbage and hallucination risk; they do not eliminate either.
`OPOS_GPU_LINK_GUARD=0` disables streamed-garbage checks and their one safer retry.
`OPOS_GPU_LINK_WATCHDOG=0` disables recovery of servers launched by this autosetup process.
`OPOS_GPU_LINK_SYSTEM_PROMPT=0` disables the default concise, grounded `demo_system_prompt.txt` instruction.
Recovery uses only owned server slots; a smaller-model fallback is limited to one swap per lane per demo.
Run these from `companion/` with your local paths; review answers and verify real phone/recovery behavior separately.
`python3 -B gpu_link_health.py preflight --offline --backend metal --binary /path/to/llama-server --model-path /path/to/model.gguf --port 38400 --receipt /tmp/gpu-link-preflight.json`
`python3 -B gpu_link_validate.py --own-server --strict-ports --llama-server /path/to/llama-server --model-file /path/to/model.gguf --model preshow-candidate --backend metal --report /tmp/gpu-link-validator.json`

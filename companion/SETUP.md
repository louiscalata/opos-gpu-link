# OPOS GPU Link setup

## Before you connect

- Use Python 3.10 or later and Android SDK Platform-Tools. The headless companion uses the Python standard library. Install Tk only if you want the optional desktop window. On macOS and Linux, the companion uses `lsof` to verify that adb owns the loopback forward. Windows uses PowerShell's TCP connection and process commands for that check.
- Run an OpenAI-compatible model server on loopback. Choose an available port such as 1235 or 8000 and note the model ID reported by the server.
- On the phone, enable Developer options and USB debugging. Use a data-capable USB cable, unlock the phone, and approve the computer's USB debugging prompt. Run `adb devices -l` to check for an authorized USB device. When using an explicit adb path, use that same executable for the check and for the companion. On Linux, your account needs permission to access the USB device. If access is denied, consult your distribution's Android USB or udev setup.
- Start the launcher as your regular user. Pairing defaults to `~/.config/opos-gpu-link` on macOS/Linux and `%LOCALAPPDATA%\OPOS\GPU Link` on Windows. New POSIX pairing directories use mode 0700 and saved key files use mode 0600. If you supply an existing POSIX directory, ensure that it is yours and has mode 0700. On Windows the saved pairing is encrypted with current-user DPAPI. For a custom Windows directory, make a best-effort check in **Properties → Security** that its ACL limits access to your user, subject to system or administrator policies.

## Start the companion

Run the commands from `companion/` and replace `MODEL_ID` with the ID your server reports.

| Platform | Command |
| --- | --- |
| macOS | `./run-mac.sh --model MODEL_ID` |
| Windows PowerShell | `.\run-windows.ps1 --model MODEL_ID` |
| Linux | `./run-linux.sh --model MODEL_ID` |

The launchers pass `--headless --always-allow`. Linux runs directly in the terminal without systemd or sudo. All three accept `--key-dir DIRECTORY`, `--serial SERIAL` and `--adb PATH`. Use `--serial` if multiple authorized USB phones are attached. Windows accepts the full path to `adb.exe` and the other platforms accept the path to `adb`. Linux checks `PATH`, then `~/Android/Sdk/platform-tools/adb`, then `/usr/bin/adb`. The `OPOS_GPU_LINK_PYTHON` environment variable overrides the launcher's Python executable.

Use `--lm-url http://127.0.0.1:8000/v1` to choose a model server, or pass the full chat-completions route with `--server`. If neither is set, the companion uses a model server it finds only when there is exactly one on an allowed port. Otherwise it keeps the existing 1235 default. Continue to pass `--model` or set `OPOS_GPU_LINK_MODEL`.

On first pairing, compare the six-digit codes and tap **Allow** on the phone. The launcher keeps its running trust grant across replug. Press Ctrl-C to stop the launcher and let it remove its own forward.

## Start at login (macOS)

To have the companion running whenever you sign in to your Mac, install the per-user LaunchAgent from `companion/`:

```
python3 gpu_link_login_agent.py install --model-path /path/to/model.gguf --serial SERIAL --adb /path/to/adb
```

It writes `~/Library/LaunchAgents/os.opos.gpulink.companion.plist`, which runs `gpu_link_autosetup.py --offline --strict-ports --own-server --port 38400` from this checkout at login, restarts it after a crash (not after a clean exit), and logs to `~/Library/Logs/OPOS GPU Link/`. No admin rights are needed. `status` shows whether it is loaded, `print` shows the plist without installing it, and `uninstall` stops and removes it. The phone still asks once before it uses a new computer.

## Find local model servers

Append `--discover` to any launcher. For example:

```sh
./run-linux.sh --discover --probe-url http://127.0.0.1:9001/v1 --json
```

This search checks each explicit `--probe-url`, a loopback `OPENAI_BASE_URL`, and the built-in loopback ports 1235 and 8000. It sends only `GET /v1/models` with a two-second timeout per address. Each result includes the server address, a best-effort server kind and model IDs. A generic result is common when a server omits identifying details. The same report shows whether `lms`, `llama-server` and `ollama` are on `PATH` and where they were found. The programs are never run.

Ports 1234, 1236, 8080, 8081, 8765, 8767, 11434, 11435 and 4173 require both an exact `--probe-url URL` and `--allow-protected-port`. To use a model server on one of these ports, also pass that same URL to `--lm-url` or `--server`. Automatic selection always skips protected ports.

## Models and memory

Keep the lead computer model in `--model`. Add up to three more models from the same OpenAI-compatible chat endpoint with repeatable `--extra-model ID:LABEL:MAKER` flags. Replace the placeholders below with IDs, labels, and makers from your local server. Quote an entry when its label or maker contains spaces. Model IDs may contain slashes. All three launchers forward the flags unchanged:

```sh
./run-linux.sh --model MODEL_ID \
  --extra-model 'EXTRA_ID:EXTRA_LABEL:EXTRA_MAKER'
```

On macOS use `./run-mac.sh` with the same arguments. On Windows PowerShell use `.\run-windows.ps1 --model MODEL_ID --extra-model 'EXTRA_ID:EXTRA_LABEL:EXTRA_MAKER'`. Use `--models-file models.json` instead of the flags to load an ordered JSON object:

```json
{"models":[{"id":"EXTRA_ID","label":"EXTRA_LABEL","maker":"EXTRA_MAKER"}]}
```

The optional `gpu` field on each JSON model can describe its computer GPU with `name` (up to 64 printable characters), `memory_mb` (nonnegative integer), and `driver` (up to 32 printable characters). The list is limited to three unique IDs, distinct from the lead model ID, and a 2,048-byte JSON file. The phone shows these models as `g1`–`g3` next to the lead `gpu` lane. A single question can start the lead, all ready extra computer lanes, and the phone lanes together. Each computer lane owns its stream and saved byte offset; the companion sends at most one text post per second per lane when fan-out is enabled, keeping the phone's existing four-posts-per-second limit.

The lead model still passes its existing model-file check. Extra model IDs are served by the existing `--lm-url` or `--server` endpoint; the companion never calls a load or unload API. Each extra model runs its one-token SSE check only on first use. While an extra model loads for the first time, its phone card says **Waiting for its turn…**. If an extra model fails that check or its stream, only that lane fails with the safe `server` code. `OPOS_GPU_LINK_REASONING_EFFORT` applies to every stream and preflight request; its default is `none`. Set it to `default` to omit the field.

LM Studio can load an available model on the first inference request when just-in-time (JIT) loading is enabled. That first request can take longer than later requests, so check that the companion's warmup completes. A standard single-model `llama-server` process loads the model it was configured with at startup. Use separately configured instances for separate models in that mode. If your llama.cpp build offers router mode, loading behavior depends on its router configuration.

Approximate starting points for one model with roughly 4-bit weights and modest context:

| Available hardware | Model size to try | Sizing considerations |
| --- | --- | --- |
| 12 GB VRAM | 7–8B | Start with one model and a short context. |
| 16 GB VRAM | 8–14B | Check headroom for cache growth before increasing context. |
| 24 GB VRAM | 14–24B | Larger models can fit depending on quantization, context and runtime overhead. |
| 64 GB unified memory | 30–32B | Leave room for the OS and other applications. Check the accelerator's working-set limit. |

Include weights, KV cache, and runtime buffers for every model that may be resident together. Reduce context, concurrency, or quantization size if warmup hits memory pressure. These ranges are estimates, with no hardware measurements in this delivery.

## Unplugging and troubleshooting

When USB disconnects, every open computer lane changes to **paused** after the link timeout and keeps its acknowledged partial text. The on-device lanes continue. On replug, the companion re-establishes its own forward and restarts the computer workers using the saved pairing. Each computer lane receives a new lease with its own saved partial and resumes from that byte offset. A new generation uses the partial answer as context, so continuation can differ from an uninterrupted stream. If no extra models are configured, the original single-lane protocol remains in use. A companion configured with extras falls back to the lead lane when an older phone refuses the extension.

- **Waiting for a phone** — check the cable and USB debugging approval. If multiple devices are authorized, use the intended USB serial explicitly.
- **Cannot verify a forward** — check that `lsof` is on `PATH` on macOS/Linux, or that Windows PowerShell can inspect local listener owners. Use the same adb executable that owns the listener.
- **No model server found** — confirm the running server's address and port and add its URL with `--probe-url`. The search expects an unauthenticated OpenAI-compatible models response. Check the port restrictions above.
- **Checking the model.** — compare the reported ID with `--model`. Check whether the model server can stream answers and has memory to load the model.
- **Replug doesn't continue the answer** — confirm that the companion is still running and that the phone retained the paused turn. See [companion pairing and recovery](README.md#start-the-companion) for pairing rejection.

## Verification for this delivery

Host tests and the public unit suites are documented in this repository ([companion tests](README.md#tests) and `android/scripts/run-host-tests.sh`). The fake LM Studio HTTP test binds an ephemeral loopback port when the host permits it. The Windows test run, USB unplug/replug, real LM Studio loading, and device rendering remain operator checks.

## LM Studio note: preload extra computer models

LM Studio's just-in-time loading keeps only one auto-loaded model at a time. If two extra models are both cold when a question arrives, loading one can evict the other and one lane fails. Before a demo, load each extra model explicitly with `lms load EXTRA_ID`. Explicitly loaded models stay resident next to the lead model. Check with `lms ps`.

## Demo guards

These guards reduce garbage and hallucination risk; they do not eliminate either.
`OPOS_GPU_LINK_GUARD=0` disables streamed-garbage checks and their one safer retry.
`OPOS_GPU_LINK_WATCHDOG=0` disables recovery of servers launched by this autosetup process.
`OPOS_GPU_LINK_SYSTEM_PROMPT=0` disables the default concise, grounded `demo_system_prompt.txt` instruction.
Recovery uses only owned server slots; a smaller-model fallback is limited to one swap per lane per demo.
Run these from `companion/` with your local paths; review answers and verify real phone/recovery behavior separately.
`python3 -B gpu_link_health.py preflight --offline --backend metal --binary /path/to/llama-server --model-path /path/to/model.gguf --port 38400 --receipt /tmp/gpu-link-preflight.json`
`python3 -B gpu_link_validate.py --own-server --strict-ports --llama-server /path/to/llama-server --model-file /path/to/model.gguf --model preshow-candidate --backend metal --report /tmp/gpu-link-validator.json`

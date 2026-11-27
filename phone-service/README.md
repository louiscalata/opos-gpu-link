# Phone service

The phone side of OPOS GPU Link. The computer companion reaches it through the USB forward; the Android app reads its state on the phone.

## Run it

Needs Python 3.11+ and nothing else (standard library only). On the phone, for example in a terminal app:

```sh
python3 -B run_link.py --label "My phone"
```

It starts two loopback servers and stops both on Ctrl-C:

- `127.0.0.1:8767`, which the computer companion reaches through the USB forward.
- `127.0.0.1:8765`, the app API the Android app reads (`GET /ai` for the session token, `GET` and `POST /api/ai`).

Pairing and answers live under `$XDG_STATE_HOME/opos` (or `--state-dir DIR`). Options: `--port`, `--app-port`, `--no-app-api`, `--label`, `--model FILE.gguf` (a model file the computer may copy) and `--state-dir`.

The phone lane is optional. To answer on the phone too, run an OpenAI-compatible server on the phone's loopback, such as llama.cpp's `llama-server`, and point the runner at it:

```sh
python3 -B run_link.py --phone-url http://127.0.0.1:8080/v1 --phone-model my-model
```

Without it, the phone lane shows as not ready and questions go to the computer.

## What's inside

- `run_link.py`: the standalone runner.
- `src/opos/gpu_link_proto.py`: the signed wire format shared with the computer.
- `src/opos/gpu_link.py`: pairing, per-lane leases, pause on cable loss and resume on replug.
- `src/opos/gpu_link_server.py`: the bounded loopback listener.
- `src/opos/link_api.py`: the app API the runner serves: the token page, the lane snapshot, ask, cancel, retry and the pairing actions, plus the optional phone lane.
- `src/opos/ai_answers.py`, `store.py`, `secure.py`: durable answers, private state files and loopback checks.
- `src/opos/ai_page.py`: the same endpoint as it runs inside the larger OPOS host app, with that app's phone models. Kept for reference; the runner doesn't use it.

## Tests

```sh
PYTHONPATH=src python3 -B -m unittest tests.test_run_link tests.test_link_api tests.test_gpu_link_proto tests.test_gpu_link_server
```

The other test files cover `ai_page.py` and need the host app.

# Phone service

The phone side of OPOS GPU Link. The PC companion reaches it through the USB forward; the Android app reads its state on the phone.

## Run it

Needs Python 3.11+ and nothing else (standard library only). On the phone, for example in a terminal app:

```sh
python3 -B run_link.py --label "My phone"
```

It listens on `127.0.0.1:8767`, keeps pairing and answers under `$XDG_STATE_HOME/opos` (or `--state-dir DIR`) and stops on Ctrl-C. Options: `--port`, `--label`, `--model FILE.gguf` (a model file the PC may copy) and `--state-dir`.

## What's inside

- `run_link.py`: the standalone runner.
- `src/opos/gpu_link_proto.py`: the signed wire format shared with the PC.
- `src/opos/gpu_link.py`: pairing, per-lane leases, pause on cable loss and resume on replug.
- `src/opos/gpu_link_server.py`: the bounded loopback listener.
- `src/opos/ai_answers.py`, `store.py`, `secure.py`: durable answers, private state files and loopback checks.
- `src/opos/ai_page.py`: the `/api/ai` endpoint the Android app calls. It still needs the larger host app, so the runner does not serve it yet.

## Tests

```sh
PYTHONPATH=src python3 -B -m unittest tests.test_run_link tests.test_gpu_link_proto tests.test_gpu_link_server
```

The other test files cover `ai_page.py` and still need the host app.

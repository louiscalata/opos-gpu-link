# Phone service

The phone side of OPOS GPU Link. The Android app talks to it on loopback; it talks to the PC companion through the USB forward.

- `gpu_link_proto.py`: the signed wire format shared with the PC.
- `gpu_link.py`: pairing, per-lane leases, pause on cable loss and resume on replug.
- `gpu_link_server.py`: the bounded loopback listener for the PC link.
- `ai_page.py`: the `/api/ai` endpoint the app calls (`ask`, `cancel`, `allow`, `deny`, `reopen`, `forget`).

These modules currently run inside a larger host process that is not published yet, and the tests import pieces of it, so they do not run on their own from this repository. A standalone runner is next.

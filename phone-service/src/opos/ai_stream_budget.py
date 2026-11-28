# SPDX-License-Identifier: Apache-2.0
"""Wall-clock budget for on-device Muse streams.

Muse's default stream deadline is 120 seconds, which is meant for short
asks. A longer on-device answer can still be streaming when that limit
arrives. Size the deadline for the requested token budget: 2 seconds per
token, plus a 120-second allowance for prompt evaluation and server start.
The worker's cancel event and Muse's idle read timeout still end a hung stream.
"""

STREAM_TOKEN_SECONDS = 2.0
STREAM_PREFILL_SECONDS = 120.0


def stream_timeout(max_tokens: int) -> float:
    """Return the Muse stream deadline in seconds for an on-device answer."""
    tokens = 0 if max_tokens < 0 else int(max_tokens)
    return STREAM_PREFILL_SECONDS + tokens * STREAM_TOKEN_SECONDS

# SPDX-License-Identifier: Apache-2.0
"""On-device Muse streams must outlive a slow last-in-queue model."""

import unittest

from opos.ai_stream_budget import (
    STREAM_PREFILL_SECONDS,
    STREAM_TOKEN_SECONDS,
    stream_timeout,
)


class StreamBudget(unittest.TestCase):
    def test_covers_granite_micro_after_a_queue_wait(self):
        # Live pull 26 Nov 2026: Granite 4.0 Micro 3B was queued during a cable
        # pull, then generated at about 3 tokens/s and was cut at Muse's 120s
        # default with 277 words / ~326 tokens and error stream_error.
        granite_tokens = 326
        self.assertGreater(stream_timeout(512), 120.0)
        self.assertGreater(stream_timeout(512), granite_tokens * STREAM_TOKEN_SECONDS)
        # 512-token pool answers (LFM2 finished with finish=length at 512)
        # need well over two minutes at on-device rates.
        self.assertEqual(stream_timeout(512), STREAM_PREFILL_SECONDS + 512 * STREAM_TOKEN_SECONDS)
        self.assertEqual(stream_timeout(512), 1144.0)

    def test_scales_with_the_token_budget_and_rejects_negative_as_zero(self):
        self.assertEqual(stream_timeout(0), STREAM_PREFILL_SECONDS)
        self.assertEqual(stream_timeout(-8), STREAM_PREFILL_SECONDS)
        self.assertEqual(stream_timeout(4096), STREAM_PREFILL_SECONDS + 4096 * STREAM_TOKEN_SECONDS)
        # Default phone-lane max_tokens is 4096; this must remain finite.
        self.assertTrue(stream_timeout(4096) < 24 * 3600)


if __name__ == "__main__":
    unittest.main()

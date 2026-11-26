package os.opos.launcher;

public final class LaneHealthTest {
    private static final String Q = "How does a pc work";

    public static void main(String[] args) {
        long t = 1_000;
        // A growing answer is never stuck.
        LaneHealth h = new LaneHealth();
        h.observeCable(true, t);
        for (int i = 0; i < 20; i++) {
            LaneHealth.Verdict v = h.observe("g1", "a1", "answering", null, 100 + i, Q, true, t);
            check(v.status == LaneHealth.Status.WORKING && !v.retryVisible);
            t += 10_000;
        }
        // Same bytes for 25 s: stuck, retry visible, automatic retry only 30 s later (last growth at t-10 s).
        LaneHealth.Verdict v = h.observe("g1", "a1", "answering", null, 119, Q, true, t + 10_000);
        check(v.status == LaneHealth.Status.WORKING);
        v = h.observe("g1", "a1", "answering", null, 119, Q, true, t + 16_000);
        check(v.status == LaneHealth.Status.STUCK && v.retryVisible && !v.autoRetryDue);
        v = h.observe("g1", "a1", "answering", null, 119, Q, true, t + 31_000);
        check(v.status == LaneHealth.Status.STUCK && !v.autoRetryDue);
        v = h.observe("g1", "a1", "answering", null, 119, Q, true, t + 46_000);
        check(v.status == LaneHealth.Status.STUCK && v.autoRetryDue);
        h.markAutoRetried("g1", Q);
        // New id after the retry: fresh clock, and the automatic retry stays spent.
        v = h.observe("g1", "a2", "answering", null, 0, Q, true, t + 47_000);
        check(v.status == LaneHealth.Status.WORKING);
        v = h.observe("g1", "a2", "answering", null, 0, Q, true, t + 120_000);
        check(v.status == LaneHealth.Status.STUCK && !v.autoRetryDue);

        // Unplugged: PC lane is Paused (retry visible, never auto, never stuck).
        h = new LaneHealth();
        t = 5_000;
        h.observeCable(false, t);
        v = h.observe("gpu", "b1", "paused", null, 500, Q, false, t + 600_000);
        check(v.status == LaneHealth.Status.PAUSED && v.retryVisible && !v.autoRetryDue);
        // Replugged: it gets 20 s from the replug (not from the pull) before it counts as stuck.
        h.observeCable(true, t + 600_000);
        v = h.observe("gpu", "b1", "paused", null, 500, Q, true, t + 610_000);
        check(v.status == LaneHealth.Status.WORKING && !v.retryVisible);
        v = h.observe("gpu", "b1", "paused", null, 500, Q, true, t + 621_000);
        check(v.status == LaneHealth.Status.STUCK && v.retryVisible && !v.autoRetryDue);
        v = h.observe("gpu", "b1", "paused", null, 500, Q, true, t + 640_000);
        check(v.retryVisible && !v.autoRetryDue);
        v = h.observe("gpu", "b1", "paused", null, 500, Q, true, t + 660_000);
        check(v.autoRetryDue);
        // It resumes by itself: bytes move, back to WORKING.
        v = h.observe("gpu", "b1", "answering", null, 700, Q, true, t + 661_000);
        check(v.status == LaneHealth.Status.WORKING && !v.retryVisible);

        // Cable state unknown: Retry is offered but never fires by itself.
        h = new LaneHealth();
        h.observe("g2", "u1", "answering", null, 10, Q, true, 0);
        v = h.observe("g2", "u1", "answering", null, 10, Q, true, 500_000);
        check(v.status == LaneHealth.Status.STUCK && v.retryVisible && !v.autoRetryDue);

        // A phone-side lane waiting for its turn is not stuck, however long it waits.
        h = new LaneHealth();
        h.observeCable(true, 0);
        v = h.observe("m3", "c1", "waiting", null, 0, Q, true, 900_000);
        check(v.status == LaneHealth.Status.WORKING && !v.retryVisible);
        // A PC lane that stays queued with the cable in and the PC ready is stuck.
        h.observe("g2", "c2", "queued", null, 0, Q, true, 0);
        v = h.observe("g2", "c2", "queued", null, 0, Q, true, 31_000);
        check(v.status == LaneHealth.Status.STUCK && v.retryVisible);
        // ...but not while the PC itself is not ready.
        h.observe("g1", "c3", "queued", null, 0, Q, false, 0);
        v = h.observe("g1", "c3", "queued", null, 0, Q, false, 100_000);
        check(v.status == LaneHealth.Status.WORKING);
        // Slow prompt processing (loading) gets 90 s.
        h.observe("m1", "c4", "loading", null, 0, Q, true, 0);
        check(h.observe("m1", "c4", "loading", null, 0, Q, true, 80_000).status
                == LaneHealth.Status.WORKING);
        check(h.observe("m1", "c4", "loading", null, 0, Q, true, 91_000).status
                == LaneHealth.Status.STUCK);
        // Phone/pool lanes never retry themselves while merely stalled.
        check(!h.observe("m1", "c4", "loading", null, 0, Q, true, 500_000).autoRetryDue);

        // Failed: retry visible. Transient error retries itself once after 3 s; other errors never.
        h = new LaneHealth();
        h.observeCable(true, 0);
        h.observe("m4", "d1", "failed", "stream_error", 1531, Q, true, 0);
        v = h.observe("m4", "d1", "failed", "stream_error", 1531, Q, true, 2_000);
        check(v.status == LaneHealth.Status.FAILED && v.retryVisible && !v.autoRetryDue);
        v = h.observe("m4", "d1", "failed", "stream_error", 1531, Q, true, 3_500);
        check(v.autoRetryDue);
        h.markAutoRetried("m4", Q);
        v = h.observe("m4", "d2", "failed", "stream_error", 10, Q, true, 100_000);
        v = h.observe("m4", "d2", "failed", "stream_error", 10, Q, true, 110_000);
        check(v.status == LaneHealth.Status.FAILED && !v.autoRetryDue);
        h.observe("m2", "e1", "failed", "low_memory", 0, Q, true, 0);
        check(!h.observe("m2", "e1", "failed", "low_memory", 0, Q, true, 60_000).autoRetryDue);
        // Not ready: no automatic retry.
        h.observe("g2", "f1", "failed", "restart", 0, Q, false, 0);
        check(!h.observe("g2", "f1", "failed", "restart", 0, Q, false, 60_000).autoRetryDue);
        // A new question gets a new budget.
        h.reset();
        h.observe("m4", "g1", "failed", "stream_error", 5, "Again", true, 0);
        check(h.observe("m4", "g1", "failed", "stream_error", 5, "Again", true, 4_000).autoRetryDue);

        // Done and cancelled show Retry (rerun) but never retry themselves.
        v = h.observe("phone", "h1", "done", null, 3162, Q, true, 0);
        check(v.status == LaneHealth.Status.DONE && v.retryVisible && !v.autoRetryDue);
        v = h.observe("m1", "h2", "cancelled", null, 191, Q, true, 0);
        check(v.status == LaneHealth.Status.CANCELLED && v.retryVisible && !v.autoRetryDue);
        // No answer: nothing to retry.
        v = h.observe("g3", "", "", null, 0, "", true, 0);
        check(v.status == LaneHealth.Status.IDLE && !v.retryVisible);
        // The clock going backwards never makes a lane stuck.
        h.observe("g1", "k1", "answering", null, 5, Q, true, 1_000_000);
        check(h.observe("g1", "k1", "answering", null, 5, Q, true, 10).status
                == LaneHealth.Status.WORKING);

        check(LaneHealth.transientError("garbled"));
        check(!LaneHealth.transientError("low_memory"));
        for (String pane : new String[]{"phone", "m4", "gpu", "g2"}) {
            h = new LaneHealth();
            h.observeCable(true, 0);
            String junk = "asks8alion".repeat(8);
            v = h.observe(pane, "bad-1", "answering", null, junk.length(), junk,
                    Q, true, 0);
            garbled(v, true);
            check(h.garbled(pane, "bad-1"));
            check(!h.garbled(pane, "another-id"));
            // The corruption stays failed if the bad tail later scrolls out of the window.
            v = h.observe(pane, "bad-1", "done", null, 10_000, "A clean-looking tail.",
                    Q, true, 1_000);
            garbled(v, true);
            // Manual Retry gets a fresh answer, but does not spend the automatic budget.
            h.markRetried(pane);
            v = h.observe(pane, "bad-2", "done", null, 200, "8".repeat(200),
                    Q, true, 2_000);
            garbled(v, true);
            h.markAutoRetried(pane, Q);
            check(h.garbled(pane, "bad-2")); // safe=1 still needed when forming Retry
            h.markRetried(pane);
            v = h.observe(pane, "bad-3", "answering", null, 200, "8".repeat(200),
                    Q, true, 3_000);
            garbled(v, false);
            v = h.observe(pane, "bad-3", "failed", "garbled", 200, "8".repeat(200),
                    Q, true, 500_000);
            garbled(v, false);
            // A good replacement ID clears the flag; another question has its own budget.
            v = h.observe(pane, "good", "done", null, 4, "Done", Q, true, 500_001);
            check(v.status == LaneHealth.Status.DONE && !v.garbled && v.error == null);
            v = h.observe(pane, "other", "done", null, 200, "8".repeat(200),
                    "Another question", true, 500_002);
            garbled(v, true);
            h.reset();
            check(!h.garbled(pane, "other"));
        }
        h = new LaneHealth();
        h.observeCable(false, 0);
        garbled(h.observe("gpu", "offline", "answering", null, 200, "8".repeat(200),
                Q, true, 0), false);
        h.observeCable(null, 1);
        garbled(h.observe("gpu", "unknown-cable", "done", null, 200, "8".repeat(200),
                Q, true, 1), false);
        garbled(h.observe("phone", "unready", "done", null, 200, "8".repeat(200),
                Q, false, 1), false);
        // Backend-provided garbled failures work even when no text was returned.
        garbled(h.observe("phone", "backend", "failed", "garbled", 0,
                Q, true, 2), true);

        System.out.println("LaneHealthTest: OK");
    }

    private static void garbled(LaneHealth.Verdict value, boolean automatic) {
        check(value.status == LaneHealth.Status.FAILED && value.garbled && value.retryVisible
                && "garbled".equals(value.error) && value.autoRetryDue == automatic);
    }

    private static void check(boolean value) { if (!value) throw new AssertionError(); }
}

package os.opos.launcher;

public final class AnswerTimingPolicyTest {
    public static void main(String[] args) {
        AnswerTimingPolicy policy = new AnswerTimingPolicy();
        equal("Done · 2.4 s", AnswerTimingPolicy.doneLabel(2400L, 0, false, false));
        equal("Done", AnswerTimingPolicy.doneLabel(null, 0, false, false));
        equal(2400L, AnswerTimingPolicy.modelDuration(2400L, 0));
        equal(3000L, AnswerTimingPolicy.comparisonFinish(3000L));
        equal(2400L, AnswerTimingPolicy.archivedDuration(2400L, 0, false, false));
        equal("", AnswerTimingPolicy.overallLabel(false));

        policy.observe("gpu", "answering", "pc-1", false, 1000L); // USB unplug
        check(policy.interrupted("pc-1"));
        check(policy.pauseMeasured("pc-1"));
        check(!policy.interrupted("phone-1"));
        equal(400L, policy.pauseMs("pc-1", 1400L));
        equal("paused", AnswerTimingPolicy.rowMarker(
                "Paused — will continue when the PC is back", true, true));
        equal("partial PC text", PcPausePolicy.textToDisplay(
                "gpu", "paused", true, "partial PC text", ""));
        policy.observe("phone", "answering", "phone-1", false, 1400L);
        check(!policy.interrupted("phone-1"));
        equal("Done · 1.0 s", AnswerTimingPolicy.doneLabel(1000L, 0, false, false));

        policy.observe("gpu", "answering", "pc-1", true, 8000L); // replug, same ID
        equal("partial PC text", PcPausePolicy.textToDisplay(
                "gpu", "answering", true, "partial PC text", ""));
        check(policy.interrupted("pc-1"));
        check(policy.pauseMeasured("pc-1"));
        equal(7000L, policy.pauseMs("pc-1", 9000L));
        equal("Done · 2.0 s", AnswerTimingPolicy.doneLabel(9000L, 7000L, true, true));
        equal(2000L, AnswerTimingPolicy.modelDuration(9000L, 7000L));
        equal(9200L, AnswerTimingPolicy.comparisonFinish(9200L));
        equal(2000L, AnswerTimingPolicy.archivedDuration(9000L, 7000L, true, true));
        equal(null, AnswerTimingPolicy.rowMarker(
                AnswerTimingPolicy.doneLabel(9000L, 7000L, true, true), true, true));
        equal(AnswerTimingPolicy.WALL_WITH_PAUSE,
                AnswerTimingPolicy.overallLabel(true));
        equal("Done · time unmeasured",
                AnswerTimingPolicy.doneLabel(9000L, 0, true, false));
        equal(-1L, AnswerTimingPolicy.archivedDuration(9000L, 0, true, false));
        equal("unmeasured", AnswerTimingPolicy.rowMarker(
                AnswerTimingPolicy.DONE_UNMEASURED, true, false));
        check(!policy.interrupted("pc-2"));
        policy.observe("gpu", "done", "pc-2", false, 9300L);
        check(!policy.interrupted("pc-2"));
        policy.clear();
        check(!policy.interrupted("pc-1"));
        check(!policy.pauseMeasured("pc-1"));

        // Unplug observed only as the Done snapshot arrives: do not charge a phantom pause.
        AnswerTimingPolicy phantom = new AnswerTimingPolicy();
        phantom.observe("gpu", "answering", "done-1", false, 5000L);
        check(phantom.interrupted("done-1"));
        phantom.observe("gpu", "done", "done-1", false, 5300L, 5100L);
        check(!phantom.interrupted("done-1"));
        equal(0L, phantom.pauseMs("done-1", 5300L));
        equal("Done · 5.1 s", AnswerTimingPolicy.doneLabel(5100L, phantom.pauseMs("done-1", 5300L),
                phantom.interrupted("done-1"), phantom.pauseMeasured("done-1")));

        // Mid-answer unplug confirmed by a later still-open snapshot, then Done:
        // clamp the pause to the finish stamp so the polling gap is not subtracted.
        AnswerTimingPolicy mid = new AnswerTimingPolicy();
        mid.observe("gpu", "answering", "mid-1", false, 1000L);
        mid.observe("gpu", "answering", "mid-1", false, 2000L);
        check(mid.interrupted("mid-1"));
        mid.observe("gpu", "done", "mid-1", true, 4000L, 2500L);
        equal(1500L, mid.pauseMs("mid-1", 4000L));
        equal("Done · 1.0 s", AnswerTimingPolicy.doneLabel(2500L, mid.pauseMs("mid-1", 4000L),
                true, true));

        // Ask sent while unplugged stays waiting after replug: keep charging pause
        // until the companion actually takes the lease.
        AnswerTimingPolicy wait = new AnswerTimingPolicy();
        wait.observe("gpu", "waiting", "wait-1", false, 1000L);
        wait.observe("gpu", "waiting", "wait-1", true, 5000L);
        check(wait.interrupted("wait-1"));
        equal(4000L, wait.pauseMs("wait-1", 5000L));
        wait.observe("gpu", "loading", "wait-1", true, 8000L);
        equal(7000L, wait.pauseMs("wait-1", 8000L));

        // Restore keeps in-flight pauses provisional: Done next does not charge a phantom.
        AnswerTimingPolicy restored = new AnswerTimingPolicy();
        java.util.Map<String, Long> starts = new java.util.HashMap<>();
        starts.put("rest-1", 1000L);
        restored.restore(java.util.Collections.singleton("rest-1"), null, starts);
        check(restored.interrupted("rest-1"));
        restored.observe("gpu", "done", "rest-1", false, 4000L, 2500L);
        check(!restored.interrupted("rest-1"));
        equal(0L, restored.pauseMs("rest-1", 4000L));

        // After restore, a later still-open snapshot confirms, then Done charges the pause.
        AnswerTimingPolicy restOpen = new AnswerTimingPolicy();
        java.util.Map<String, Long> startsOpen = new java.util.HashMap<>();
        startsOpen.put("rest-2", 1000L);
        restOpen.restore(java.util.Collections.singleton("rest-2"), null, startsOpen);
        restOpen.observe("gpu", "answering", "rest-2", false, 2000L);
        restOpen.observe("gpu", "done", "rest-2", true, 4000L, 2500L);
        equal(1500L, restOpen.pauseMs("rest-2", 4000L));

        // Confirmed pause whose finish is not after the start is a phantom.
        AnswerTimingPolicy stale = new AnswerTimingPolicy();
        stale.observe("gpu", "answering", "stale-1", false, 3000L);
        stale.observe("gpu", "answering", "stale-1", false, 4000L);
        stale.observe("gpu", "done", "stale-1", false, 4500L, 2000L);
        check(!stale.interrupted("stale-1"));
        equal(0L, stale.pauseMs("stale-1", 4500L));

        System.out.println("AnswerTimingPolicyTest: OK");
    }

    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError(expected + " != " + actual);
        }
    }
}

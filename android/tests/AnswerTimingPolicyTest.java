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
        System.out.println("AnswerTimingPolicyTest: OK");
    }

    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError(expected + " != " + actual);
        }
    }
}

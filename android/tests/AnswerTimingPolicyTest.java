package os.opos.launcher;

public final class AnswerTimingPolicyTest {
    public static void main(String[] args) {
        AnswerTimingPolicy policy = new AnswerTimingPolicy();
        equal("Done · 2.4 s", AnswerTimingPolicy.doneLabel(2400L, false));
        equal("Done", AnswerTimingPolicy.doneLabel(null, false));
        equal(2400L, AnswerTimingPolicy.modelDuration(2400L, false));
        equal(3000L, AnswerTimingPolicy.comparisonFinish(3000L, false));
        equal(2400L, AnswerTimingPolicy.archivedDuration(2400L, false));
        equal("", AnswerTimingPolicy.overallLabel(false));

        policy.observe("gpu", "answering", "pc-1", false); // USB unplug
        check(policy.interrupted("pc-1"));
        check(!policy.interrupted("phone-1"));
        equal("paused", AnswerTimingPolicy.rowMarker(
                "Paused — will continue when the PC is back", true));
        equal("partial PC text", PcPausePolicy.textToDisplay(
                "gpu", "paused", true, "partial PC text", ""));
        policy.observe("phone", "answering", "phone-1", false);
        check(!policy.interrupted("phone-1"));
        equal("Done · 1.0 s", AnswerTimingPolicy.doneLabel(1000L, false));

        policy.observe("gpu", "answering", "pc-1", true); // replug, same ID
        equal("partial PC text", PcPausePolicy.textToDisplay(
                "gpu", "answering", true, "partial PC text", ""));
        check(policy.interrupted("pc-1"));
        equal("Done · time unmeasured", AnswerTimingPolicy.doneLabel(9000L, true));
        equal(null, AnswerTimingPolicy.modelDuration(9000L, true));
        equal(null, AnswerTimingPolicy.comparisonFinish(9200L, true));
        equal(-1L, AnswerTimingPolicy.archivedDuration(9000L, true));
        equal("unmeasured", AnswerTimingPolicy.rowMarker(
                AnswerTimingPolicy.doneLabel(9000L, true), true));
        equal(AnswerTimingPolicy.WALL_WITH_PAUSE,
                AnswerTimingPolicy.overallLabel(true));
        check(!policy.interrupted("pc-2"));
        policy.observe("gpu", "done", "pc-2", false);
        check(!policy.interrupted("pc-2"));
        policy.clear();
        check(!policy.interrupted("pc-1"));
        System.out.println("AnswerTimingPolicyTest: OK");
    }

    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError(expected + " != " + actual);
        }
    }
}

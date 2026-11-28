package os.opos.launcher;

public final class LiveSpeedLabelTest {
    public static void main(String[] args) {
        equal("17 tokens a second · this run", speed(17, "answering", true, "Streaming…"));
        equal("2.5 tokens a second · this run", speed(2.5, "answering", true, "Streaming…"));
        equal("1 token a second · this run", speed(1, "answering", true, "Streaming…"));
        equal("", speed(17, "done", true, "Done"));
        equal("", speed(17, "answering", false, "Streaming…"));
        equal("", speed(17, "answering", true, "Paused. Resumes when the computer is back."));
        equal("", speed(17, "answering", true, "Checking MacBook connection…"));
        equal("", speed(17, "answering", true, "Thinking…"));
        equal("", speed(17, "answering", true, "Could not read answer · Retry"));
        equal("", speed(0, "answering", true, "Streaming…"));
        equal("", speed(-1, "answering", true, "Streaming…"));
        equal("", speed(Double.NaN, "answering", true, "Streaming…"));
        equal("", speed(Double.POSITIVE_INFINITY, "answering", true, "Streaming…"));
        equal("", speed(1e-5, "answering", true, "Streaming…"));
        equal("", speed(1e7, "answering", true, "Streaming…"));
        equal("", speed("17", "answering", true, "Streaming…"));
        equal("", speed(null, "answering", true, "Streaming…"));
        equal("", speed(Long.MAX_VALUE, "answering", true, "Streaming…"));
        System.out.println("LiveSpeedLabelTest: OK");
    }

    private static String speed(Object reported, String state, boolean answerVisible,
                                String displayedState) {
        return LiveSpeedLabel.text(reported, state, answerVisible, displayedState, "Streaming…");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

package os.opos.launcher;

public final class WorkingIndicatorTest {
    public static void main(String[] args) {
        check(WorkingIndicator.working("Streaming…"), "streaming works");
        check(WorkingIndicator.working("Thinking…"), "thinking works");
        check(WorkingIndicator.working("  Streaming…"), "leading space");
        for (String s : new String[] {null, "", "Paused — will continue when the MacBook is back",
                "Done 28.4 s", "Done", "Stopped", "Failed — model stopped", "Waiting for its turn…",
                "Ready to ask", "Not asked this time", "streaming"}) {
            check(!WorkingIndicator.working(s), "not working: " + s);
        }
        equal("● ▁ Working…", WorkingIndicator.line(0, 0, false, false));
        equal("● ▂ Working… · 1 word", WorkingIndicator.line(1, 1, false, false));
        equal("● ▁ Working… · 312 words", WorkingIndicator.line(WorkingIndicator.SPINNER.length(), 312, false, false));
        equal("● ▂ Working…", WorkingIndicator.line(-WorkingIndicator.SPINNER.length() + 1, -4, false, false));
        equal("● Working… · 684 words", WorkingIndicator.line(7, 684, true, false));
        equal("● Working…", WorkingIndicator.line(3, 0, true, false));
        equal("● ▃ 1234 words", WorkingIndicator.line(2, 1234, false, true));
        equal("● 1 word", WorkingIndicator.line(2, 1, true, true));
        equal("● ▃ Working…", WorkingIndicator.line(2, 0, false, true));
        String extreme = WorkingIndicator.line(Long.MIN_VALUE, 0, false, false);
        check(WorkingIndicator.SPINNER.indexOf(extreme.charAt(2)) >= 0, "any long tick is a frame");
        for (String s : new String[] {"Streaming paused", "Streaming failed", "Thinking stopped",
                "Streaming… paused"}) {
            check(!WorkingIndicator.working(s), "qualified label is not live: " + s);
        }
        // Every frame is one character and different from the next, so the bar visibly moves.
        String sp = WorkingIndicator.SPINNER;
        for (int i = 0; i < sp.length(); i++) {
            check(!Character.isSurrogate(sp.charAt(i)), "single char frame");
            check(sp.charAt(i) != sp.charAt((i + 1) % sp.length()), "frame changes");
        }
        check(WorkingIndicator.dotBright(0, false) && !WorkingIndicator.dotBright(4, false)
                && WorkingIndicator.dotBright(8, false), "dot pulses");
        for (int t = 0; t < 16; t++) check(WorkingIndicator.dotBright(t, true), "steady dot");
        check(WorkingIndicator.TICK_MS >= 100, "not faster than 10 fps");
        System.out.println("WorkingIndicatorTest OK");
    }

    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected <" + expected + "> but was <" + actual + ">");
        }
    }

    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
}

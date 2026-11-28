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
        equal("● ▁ Streaming…", WorkingIndicator.line(0, "Streaming…", 0, false));
        equal("● ▂ Streaming… · 1 word", WorkingIndicator.line(1, "Streaming…", 1, false));
        equal("● ▁ Streaming… · 312 words", WorkingIndicator.line(WorkingIndicator.SPINNER.length(), "Streaming…", 312, false));
        equal("● ▂ Thinking…", WorkingIndicator.line(-WorkingIndicator.SPINNER.length() + 1, "Thinking…", -4, false));
        equal("● Streaming… · 684 words", WorkingIndicator.line(7, "Streaming…", 684, true));
        equal("● Thinking…", WorkingIndicator.line(3, "Thinking…", 0, true));
        equal("● ▃ Streaming… · 1234 words", WorkingIndicator.line(2, "Streaming…", 1234, false));
        equal("● Streaming… · 1 word", WorkingIndicator.line(2, "Streaming…", 1, true));
        equal("Streaming", WorkingIndicator.spoken("  Streaming…  ", 0));
        equal("Streaming, 1 word", WorkingIndicator.spoken("Streaming…", 1));
        equal("Streaming, 12 words", WorkingIndicator.spoken("  Streaming…  ", 12));
        equal("Thinking", WorkingIndicator.spoken("Thinking…", -4));
        equal("", WorkingIndicator.spoken(null, 5));
        equal("", WorkingIndicator.spoken("   ", 5));
        equal("", WorkingIndicator.line(0, null, 5, false));
        equal("", WorkingIndicator.line(0, "   ", 5, false));
        String extreme = WorkingIndicator.line(Long.MIN_VALUE, "Streaming…", 0, false);
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

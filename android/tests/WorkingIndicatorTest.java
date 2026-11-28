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
        equal("● Working...", WorkingIndicator.line("Streaming…"));
        equal("● Working...", WorkingIndicator.line("Thinking…"));
        equal("", WorkingIndicator.line("Stopped"));
        equal("", WorkingIndicator.count(0));
        equal("", WorkingIndicator.count(-4));
        equal(" · 1 word", WorkingIndicator.count(1));
        equal(" · 312 words", WorkingIndicator.count(312));
        equal("Working...", WorkingIndicator.display("Streaming…"));
        equal("Working...", WorkingIndicator.display("Thinking…"));
        equal("Paused", WorkingIndicator.display("Paused"));
        equal("Working", WorkingIndicator.spoken("  Streaming…  ", 0));
        equal("Working, 1 word", WorkingIndicator.spoken("Streaming…", 1));
        equal("Working, 12 words", WorkingIndicator.spoken("  Streaming…  ", 12));
        equal("Working", WorkingIndicator.spoken("Thinking…", -4));
        equal("", WorkingIndicator.spoken(null, 5));
        equal("", WorkingIndicator.spoken("   ", 5));
        equal("", WorkingIndicator.line(null));
        equal("", WorkingIndicator.line("   "));
        for (String s : new String[] {"Streaming paused", "Streaming failed", "Thinking stopped",
                "Streaming… paused"}) {
            check(!WorkingIndicator.working(s), "qualified label is not live: " + s);
        }
        near(1f, WorkingIndicator.dotAlpha(0f, false));
        near(0.71f, WorkingIndicator.dotAlpha(0.25f, false));
        near(0.42f, WorkingIndicator.dotAlpha(0.5f, false));
        near(1f, WorkingIndicator.dotAlpha(1f, false));
        check(WorkingIndicator.dotAlpha(0.1f, false)
                > WorkingIndicator.dotAlpha(0.2f, false), "dot fades smoothly");
        for (int dot = 0; dot < WorkingIndicator.DOT_COUNT; dot++) {
            near(1f, WorkingIndicator.trailingAlpha(dot / 3f, dot, false));
            near(1f, WorkingIndicator.trailingAlpha(0.37f, dot, true));
        }
        check(WorkingIndicator.trailingAlpha(0f, 0, false)
                > WorkingIndicator.trailingAlpha(0f, 1, false), "first trailing dot leads");
        check(WorkingIndicator.trailingAlpha(1f / 3f, 1, false)
                > WorkingIndicator.trailingAlpha(1f / 3f, 0, false), "second dot follows");
        near(1f, WorkingIndicator.dotAlpha(0.37f, true));
        check(WorkingIndicator.animate(true, true, true, false, true), "live visible lane animates");
        check(!WorkingIndicator.animate(false, true, true, false, true), "stopped lane is static");
        check(!WorkingIndicator.animate(true, false, true, false, true), "off-screen lane is static");
        check(!WorkingIndicator.animate(true, true, false, false, true), "paused activity is static");
        check(!WorkingIndicator.animate(true, true, true, true, true), "reduce motion is static");
        check(!WorkingIndicator.animate(true, true, true, false, false), "disabled animators are static");
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

    private static void near(float expected, float actual) {
        if (Math.abs(expected - actual) > 0.0001f) {
            throw new AssertionError("expected " + expected + " but was " + actual);
        }
    }
}

package os.opos.launcher;

public final class ScrollPolicyTest {
    public static void main(String[] args) {
        // maxScroll counts padding like ScrollView does (finding 3c).
        equal(200, ScrollPolicy.maxScroll(1000, 800, 0, 0));
        equal(223, ScrollPolicy.maxScroll(1000, 800, 0, 23));
        equal(230, ScrollPolicy.maxScroll(1000, 800, 7, 23));
        equal(0, ScrollPolicy.maxScroll(500, 800, 0, 23));
        equal(0, ScrollPolicy.maxScroll(0, 0, 0, 0));
        equal(1000, ScrollPolicy.maxScroll(1000, 10, 40, 40));

        // Tail follow lands exactly on the end, even when it is not a line top (finding 3b).
        int[] tops = {0, 40, 64, 88, 112, 200, 224};
        equal(210, ScrollPolicy.targetScroll(Integer.MAX_VALUE, 210, tops));
        equal(210, ScrollPolicy.targetScroll(210, 210, tops));
        equal(210, ScrollPolicy.targetScroll(500, 210, tops));
        // The old behaviour floored 210 to the line top 200, hiding 10 px of the newest line.
        equal(200, LineSnap.snapTop(210, tops));
        // A pane mid-answer still snaps to a whole line.
        equal(88, ScrollPolicy.targetScroll(100, 210, tops));
        equal(0, ScrollPolicy.targetScroll(-5, 210, tops));
        equal(0, ScrollPolicy.targetScroll(50, 0, tops));

        // A pane that stays paused is not re-aligned every poll (finding 3a).
        equal(false, ScrollPolicy.shouldAlign(false, false, false, false));
        equal(true, ScrollPolicy.shouldAlign(false, false, true, false));
        equal(false, ScrollPolicy.shouldAlign(false, false, true, true));
        equal(true, ScrollPolicy.shouldAlign(true, false, false, false));
        equal(true, ScrollPolicy.shouldAlign(false, true, false, true));
        // Simulated poll loop: entering pause aligns once, then 50 more polls do nothing.
        String last = "streaming";
        int aligns = 0;
        for (int poll = 0; poll < 51; poll++) {
            String now = "paused";
            boolean reachedPaused = "paused".equals(now) && !"paused".equals(last);
            if (ScrollPolicy.shouldAlign(false, false, reachedPaused, false)) aligns++;
            last = now;
        }
        equal(1, aligns);
        System.out.println("ScrollPolicyTest: OK");
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }

    private static void equal(boolean expected, boolean actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

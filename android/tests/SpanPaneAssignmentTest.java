package os.opos.launcher;

/**
 * Tests for SpanPaneAssignment.
 */
public final class SpanPaneAssignmentTest {
    public static void main(String[] args) {
        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.MASTHEAD, SpanPolicy.Mode.NONE) == SpanPaneAssignment.Pane.LEFT);
        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.ANSWERS, SpanPolicy.Mode.NONE) == SpanPaneAssignment.Pane.LEFT);
        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.COMPOSER, SpanPolicy.Mode.NONE) == SpanPaneAssignment.Pane.LEFT);
        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.STATS, SpanPolicy.Mode.NONE) == SpanPaneAssignment.Pane.LEFT);
        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.HEAT, SpanPolicy.Mode.NONE) == SpanPaneAssignment.Pane.LEFT);
        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.WORKING, SpanPolicy.Mode.NONE) == SpanPaneAssignment.Pane.LEFT);

        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.MASTHEAD, SpanPolicy.Mode.SIDE_BY_SIDE) == SpanPaneAssignment.Pane.LEFT);
        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.ANSWERS, SpanPolicy.Mode.SIDE_BY_SIDE) == SpanPaneAssignment.Pane.LEFT);
        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.COMPOSER, SpanPolicy.Mode.SIDE_BY_SIDE) == SpanPaneAssignment.Pane.LEFT);

        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.STATS, SpanPolicy.Mode.SIDE_BY_SIDE) == SpanPaneAssignment.Pane.RIGHT);
        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.HEAT, SpanPolicy.Mode.SIDE_BY_SIDE) == SpanPaneAssignment.Pane.RIGHT);
        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.WORKING, SpanPolicy.Mode.SIDE_BY_SIDE) == SpanPaneAssignment.Pane.RIGHT);

        check(SpanPaneAssignment.paneFor(SpanPaneAssignment.Section.STATS, null) == SpanPaneAssignment.Pane.LEFT);

        System.out.println("SpanPaneAssignmentTest: OK");
    }

    private static void check(boolean value) {
        if (!value) {
            throw new AssertionError();
        }
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) {
            throw new AssertionError(expected + " != " + actual);
        }
    }
}

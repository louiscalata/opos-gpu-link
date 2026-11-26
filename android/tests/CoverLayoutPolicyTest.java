package os.opos.launcher;

public final class CoverLayoutPolicyTest {
    public static void main(String[] args) {
        equal(62, CoverLayoutPolicy.mastheadHeightDp(true, false));
        equal(0, CoverLayoutPolicy.mastheadHeightDp(true, true));
        equal(62, CoverLayoutPolicy.mastheadHeightDp(false, true));
        equal(64, CoverLayoutPolicy.composerRowHeightDp(true, false));
        equal(48, CoverLayoutPolicy.composerRowHeightDp(true, true));
        equal(64, CoverLayoutPolicy.composerRowHeightDp(false, true));
        // Illustrative 210 dp viewport and 98 dp sticky chrome, not a device
        // measurement: compacting the composer leaves the 64 dp target.
        equal(64, CoverLayoutPolicy.resultsSpaceDp(210, 98, true, true));
        equal(0, CoverLayoutPolicy.resultsSpaceDp(130, 98, true, true));
        equal(0, CoverLayoutPolicy.resultsSpaceDp(210, 98, true, false));
        check(CoverLayoutPolicy.showTitleRow(64, true));
        check(!CoverLayoutPolicy.showTitleRow(63, true));
        check(!CoverLayoutPolicy.showTitleRow(110, false));
        check(CoverLayoutPolicy.showTitleRow(118, false));
        System.out.println("CoverLayoutPolicyTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

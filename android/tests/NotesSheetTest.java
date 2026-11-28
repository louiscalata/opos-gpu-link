package os.opos.launcher;

public final class NotesSheetTest {
    public static void main(String[] args) {
        check(NotesSheet.available(false));
        check(NotesSheet.available(true));
        equal(0, NotesSheet.noteCount(null));
        equal(0, NotesSheet.noteCount(""));
        equal(0, NotesSheet.noteCount("   \n  "));
        equal(1, NotesSheet.noteCount("A single note"));
        equal(2, NotesSheet.noteCount("First note\n\nSecond note"));
        equal(3, NotesSheet.noteCount("One\n\n\nTwo\n\nThree"));
        equal("NOTES", NotesSheet.tabLabel(0));
        equal("NOTES · 2", NotesSheet.tabLabel(2));
        equal(NotesSheet.State.HALF, NotesSheet.onTabTap(NotesSheet.State.COLLAPSED));
        equal(NotesSheet.State.COLLAPSED, NotesSheet.onTabTap(NotesSheet.State.HALF));
        equal(NotesSheet.State.COLLAPSED, NotesSheet.onTabTap(NotesSheet.State.FULL));
        equal(36, NotesSheet.height(NotesSheet.State.COLLAPSED, 36, 200, 400));
        equal(200, NotesSheet.height(NotesSheet.State.HALF, 36, 200, 400));
        equal(400, NotesSheet.height(NotesSheet.State.FULL, 36, 200, 400));
        equal(200, NotesSheet.halfHeight(400, 36));
        equal(400, NotesSheet.fullHeight(400, 36));
        equal(NotesSheet.State.COLLAPSED, NotesSheet.snap(40, 36, 200, 400, 0));
        equal(NotesSheet.State.HALF, NotesSheet.snap(180, 36, 200, 400, 0));
        equal(NotesSheet.State.FULL, NotesSheet.snap(360, 36, 200, 400, 0));
        equal(NotesSheet.State.HALF, NotesSheet.snap(36, 36, 200, 400, -800));
        equal(NotesSheet.State.FULL, NotesSheet.snap(200, 36, 200, 400, -800));
        equal(NotesSheet.State.HALF, NotesSheet.snap(400, 36, 200, 400, 800));
        equal(NotesSheet.State.COLLAPSED, NotesSheet.snap(200, 36, 200, 400, 800));
        equal("Saved to Notes", NotesSheet.CONFIRMATION);
        equal(36, NotesSheet.TAB_DP);
        equal(80, NotesSheet.dockInset(40, 80, 0));
        equal(100, NotesSheet.dockInset(40, 80, 100));
        equal(36, NotesSheet.TAB_DP);
        equal(56, NotesSheet.SUMMARY_MIN_DP);
        equal(48, NotesSheet.TAB_TOUCH_DP);
        equal(12, NotesSheet.TAB_SLOP_DP);
        equal(104, NotesSheet.CONTENT_BOTTOM_PAD_DP);
        equal(0, NotesSheet.contentBottomPad(0, 0));
        equal(92, NotesSheet.contentBottomPad(36, 56));
        equal(200, NotesSheet.contentBottomPad(120, 80));
        equal(0, NotesSheet.contentBottomPad(36, 56, 92));
        equal(164, NotesSheet.contentBottomPad(200, 56, 92));
        equal(72, NotesSheet.summaryMaxDp(true));
        equal(140, NotesSheet.summaryMaxDp(false));
        equal(48, NotesSheet.summaryMaxDp(false, true));
        equal(48, NotesSheet.summaryMaxDp(false, true, false));
        equal(140, NotesSheet.summaryMaxDp(false, true, true));
        equal(72, NotesSheet.summaryMaxDp(true, false, true));
        check(NotesSheet.summaryOpensFullPage(false));
        check(!NotesSheet.summaryOpensFullPage(true));
        equal(48, NotesSheet.summaryMinDp(true));
        equal(0, NotesSheet.collapsedTabHeightPx(
                CoverScreenPolicy.select(880, 360, 0) == CoverScreenPolicy.Mode.WIDE, 0, 48));
        equal(0, NotesSheet.collapsedTabHeightPx(
                CoverScreenPolicy.select(1024, 419, 0) == CoverScreenPolicy.Mode.WIDE, 0, 48));
        equal(48, NotesSheet.collapsedTabHeightPx(
                CoverScreenPolicy.select(360, 880, 0) == CoverScreenPolicy.Mode.WIDE, 0, 48));
        equal(48, NotesSheet.collapsedTabHeightPx(
                CoverScreenPolicy.select(374, 360, 1) == CoverScreenPolicy.Mode.WIDE, 0, 48));
        equal(0, NotesSheet.collapsedTabHeightPx(true, 72, 48));
        equal(48, NotesSheet.collapsedTabHeightPx(false, 0, 48));
        equal(48, NotesSheet.collapsedTabHeightPx(false, 36, 48));
        equal(72, NotesSheet.collapsedTabHeightPx(false, 72, 48));
        equal(56, NotesSheet.summaryMinDp(false));
        equal(48, NotesSheet.summaryHeight(140,
                NotesSheet.summaryMinDp(true), NotesSheet.summaryMaxDp(false, true)));
        equal(56, NotesSheet.summaryHeight(0, 56, 72));
        equal(72, NotesSheet.summaryHeight(200, 56, 72));
        equal(56, NotesSheet.summaryHeight(40, 56, 72));
        System.out.println("NotesSheetTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected " + expected + ", got " + actual);
        }
    }
    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
    private static void equal(NotesSheet.State expected, NotesSheet.State actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

package os.opos.launcher;

public final class NotesCompactTest {
    public static void main(String[] args) {
        check(NotesCompact.empty(null));
        check(NotesCompact.empty(""));
        check(NotesCompact.empty("  \n "));
        check(!NotesCompact.empty("buy cables"));
        // The empty card reserves no height of its own and does not rule a blank page.
        equal(0, NotesCompact.cardMinDp(""));
        equal(0, NotesCompact.cardMinDp("x"));
        check(!NotesCompact.drawFillerRules(""));
        check(NotesCompact.drawFillerRules("a note"));
        // One writing line, far under the 160 dp card the empty NOTES used to reserve.
        check(NotesCompact.editorMinDp("") <= 48);
        check(NotesCompact.editorMinDp("") >= 32);
        equal("Tap to add a note", NotesCompact.EMPTY_HINT);
        System.out.println("NotesCompactTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

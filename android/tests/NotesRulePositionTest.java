package os.opos.launcher;

public final class NotesRulePositionTest {
    public static void main(String[] args) {
        equal(104, NotesRulePosition.ruleY(100, 108, 48));
        equal(106, NotesRulePosition.ruleY(100, 130, 48));
        equal(100, NotesRulePosition.ruleY(100, 99, 48));
        try {
            NotesRulePosition.ruleY(100, 108, 0);
            throw new AssertionError("Expected invalid line height");
        } catch (IllegalArgumentException expected) {
            // A nonpositive line height cannot space continued rules.
        }
        System.out.println("NotesRulePositionTest: OK");
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

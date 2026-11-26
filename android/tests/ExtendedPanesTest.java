package os.opos.launcher;

import java.util.Arrays;

public final class ExtendedPanesTest {
    public static void main(String[] args) {
        for (String pane : new String[]{"g1", "g2", "g3"}) {
            check(PaneKeys.valid(pane));
            check(PaneKeys.extra(pane));
            check(PaneKeys.pc(pane));
            check(PaneKeys.modelKindMatches(pane, "pc"));
            check(!PaneKeys.modelKindMatches(pane, "phone"));
            equal("PC GPU", PaneKeys.kicker(pane));
            equal("on the PC's GPU", PaneKeys.defaultWhere(pane));
        }
        equal("PC GPU", PaneKeys.kicker("gpu"));
        equal("MODEL", PaneKeys.kicker("phone"));
        equal("MODEL", PaneKeys.kicker("m1"));
        equal("on this phone", PaneKeys.defaultWhere("m1"));
        check(PaneKeys.modelKindMatches("m1", "phone"));
        check(!PaneKeys.modelKindMatches("m1", "pc"));
        check(PaneKeys.modelKindMatches("m1", ""));
        check(!PaneKeys.modelKindMatches("g4", "pc"));
        check(!PaneKeys.valid("g4"));
        equal(Arrays.asList("phone", "gpu", "m1", "g2", "g1"),
                PaneKeys.orderedPanes(Arrays.asList("m1", "g2", "g1", "g2")));
        equal(9, NewspaperLayoutDecision.articleSlotsExtended(9, false).length);
        equal(9, NewspaperLayoutDecision.articleSlotsExtended(9, true).length);
        try {
            NewspaperLayoutDecision.articleSlotsExtended(10, false);
            throw new AssertionError("Ten lanes accepted");
        } catch (IllegalArgumentException expected) {}
        System.out.println("ExtendedPanesTest: OK");
    }
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

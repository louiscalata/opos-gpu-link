package os.opos.launcher;

public final class ComputerWordsTest {
    public static void main(String[] args) {
        equal("MacBook", ComputerWords.noun("M5 Pro MacBook Pro"));
        equal("Mac", ComputerWords.noun("M4 Mac mini"));
        equal("Mac", ComputerWords.noun("iMac"));
        equal("PC", ComputerWords.noun("M5 Pro PC"));
        equal("PC", ComputerWords.noun("RTX 5080 PC"));
        equal("PC", ComputerWords.noun("Macro PC")); // whole words only
        equal("PC", ComputerWords.noun(null));

        equal("MacBook GPU", ComputerWords.apply("PC GPU", "MacBook"));
        equal("on the MacBook's GPU", ComputerWords.apply("on the PC's GPU", "MacBook"));
        equal("Paused — will continue when the MacBook is back",
                ComputerWords.apply("Paused — will continue when the PC is back", "MacBook"));
        equal("MacBook\u00a0waiting\nPhone\u00a0waiting",
                ComputerWords.apply("PC\u00a0waiting\nPhone\u00a0waiting", "MacBook"));
        equal(" · PHONE + MACBOOK GPU EDITION",
                ComputerWords.apply(" · PHONE + PC GPU EDITION", "MacBook"));
        equal("PCs and PCIe stay", ComputerWords.apply("PCs and PCIe stay", "Mac"));
        equal("Allow this PC", ComputerWords.apply("Allow this PC", "PC"));

        ComputerWords.set("PC");
        check(!ComputerWords.observe(""));
        check(ComputerWords.observe("M5 Pro MacBook Pro"));
        equal("MacBook", ComputerWords.current());
        check(!ComputerWords.observe("M5 Pro MacBook Pro"));
        equal("MacBook GPU", PaneKeys.kicker("gpu"));
        equal("MODEL", PaneKeys.kicker("phone"));
        check(ComputerWords.observe("RTX 5080 PC"));
        equal("PC GPU", PaneKeys.kicker("gpu"));
        equal("PC", ComputerWords.noun("RTX 5080 PC"));
        equal("text", ComputerWords.apply("text", null));
        ComputerWords.set("MacBook");
        equal("on the MacBook's GPU", PaneKeys.shownWhere("gpu", "on the PC's GPU"));
        equal("on the MacBook's GPU", PaneKeys.shownWhere("gpu", ""));
        equal("M5 Pro MacBook Pro", PaneKeys.shownWhere("gpu", "M5 Pro MacBook Pro"));
        equal("on this phone", PaneKeys.shownWhere("phone", "unknown"));
        check(Dateline.format(java.time.LocalDate.of(2026, 12, 10), "PC").endsWith("PHONE + PC GPU EDITION"));
        check(Dateline.format(java.time.LocalDate.of(2026, 12, 10)).endsWith("PHONE + MACBOOK GPU EDITION"));
        ComputerWords.set("bogus");
        equal("PC", ComputerWords.current());
        System.out.println("ComputerWordsTest: OK");
    }

    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected <" + expected + "> but was <" + actual + ">");
        }
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError("check failed");
    }
}

package os.opos.launcher;

import java.util.Arrays;
import java.util.List;

public final class PcPausePolicyTest {
    public static void main(String[] args) {
        for (String pane : new String[]{"gpu", "g1", "g2", "g3"}) {
            check(PcPausePolicy.paused(pane, "answering", false));
            check(PcPausePolicy.paused(pane, "queued", false));
            check(PcPausePolicy.paused(pane, "paused", true));
            check(!PcPausePolicy.paused(pane, "answering", true));
            equal("partial text", PcPausePolicy.textToDisplay(
                    pane, "paused", true, "partial text", ""));
            equal("resumed text", PcPausePolicy.textToDisplay(
                    pane, "answering", true, "partial text", "resumed text"));
            equal("", PcPausePolicy.textToDisplay(
                    pane, "answering", false, "previous question", ""));
            equal("", PcPausePolicy.textToDisplay(
                    pane, "done", true, "old text", ""));
        }
        check(!PcPausePolicy.paused("phone", "answering", false));
        equal("", PcPausePolicy.textToDisplay(
                "phone", "answering", true, "old text", ""));
        List<String> shown = Arrays.asList("gpu", "phone", "g1", "g2", "g3");
        List<String> snapshotSelected = Arrays.asList("gpu", "phone");
        equal(shown, PcPausePolicy.visiblePanes(shown, snapshotSelected, false));
        equal(snapshotSelected, PcPausePolicy.visiblePanes(shown, snapshotSelected, true));
        System.out.println("PcPausePolicyTest: OK");
    }

    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

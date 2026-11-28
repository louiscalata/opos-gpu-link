package os.opos.launcher;

public final class AnswerDisplayTest {
    public static void main(String[] args) {
        equal("", AnswerDisplay.text("phone", null));
        equal("", AnswerDisplay.text("m1", " \t\n"));
        equal("CUDA cores, and more", AnswerDisplay.text("phone", " CUDA cores, and more"));
        equal("A GPU, and more", AnswerDisplay.text("m2", "\n\t A GPU, and more"));
        equal("first  second\n", AnswerDisplay.text("m3", "  first  second\n"));
        equal("LFM2 1.2B", AnswerDisplay.text("m3", "\u2003LFM2 1.2B"));
        equal("Granite 4.1 3B", AnswerDisplay.text("m4", "\u2003Granite 4.1 3B"));
        equal("answer", AnswerDisplay.text("m1", "\u2003\tanswer"));
        equal("\u200banswer", AnswerDisplay.text("m1", " \u200banswer"));
        // Repeated streamed snapshots remain clean without changing later spacing.
        equal("", AnswerDisplay.text("phone", " "));
        equal("CUDA", AnswerDisplay.text("phone", " CUDA"));
        equal("CUDA cores", AnswerDisplay.text("phone", " CUDA cores"));
        // Computer lanes use the same clean start, including streamed snapshots.
        for (String pane : new String[] {"gpu", "g1", "g2", "g3"}) {
            equal("", AnswerDisplay.text(pane, " \t\n"));
            equal("", AnswerDisplay.text(pane, " \n"));
            equal("Nemotron", AnswerDisplay.text(pane, " \n  Nemotron"));
            equal("Nemotron 3.5 Bolt", AnswerDisplay.text(pane, " \n  Nemotron 3.5 Bolt"));
            equal("first\n  - nested", AnswerDisplay.text(pane, "\n  first\n  - nested"));
        }
        // An answer starting with a list keeps its intentional indentation.
        equal("  - first\n    - second", AnswerDisplay.text("gpu", "\n  - first\n    - second"));
        equal("  1. first", AnswerDisplay.text("m1", " \n  1. first"));
        System.out.println("AnswerDisplayTest: OK");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

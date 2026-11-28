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
        // Computer answers keep their original indentation.
        equal("  indented", AnswerDisplay.text("gpu", "  indented"));
        equal("\n  indented", AnswerDisplay.text("g1", "\n  indented"));
        System.out.println("AnswerDisplayTest: OK");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

package os.opos.launcher;

public final class QuestionHeadlineTest {
    public static void main(String[] args) {
        String prefix = "You asked: ";
        equal(11, QuestionHeadline.prefixLength("You asked: what is a GPU?", prefix));
        equal(11, QuestionHeadline.prefixLength("You asked: ", prefix));
        // Headlines without the label must not lose their first 11 characters (finding 5).
        equal(0, QuestionHeadline.prefixLength("Explain USB-C power delivery", prefix));
        equal(0, QuestionHeadline.prefixLength("You asked", prefix));
        equal(0, QuestionHeadline.prefixLength("you asked: lower case", prefix));
        equal(0, QuestionHeadline.prefixLength("", prefix));
        equal(0, QuestionHeadline.prefixLength(null, prefix));
        equal(0, QuestionHeadline.prefixLength("You asked: x", ""));
        equal(0, QuestionHeadline.prefixLength("You asked: x", null));
        equal(2, QuestionHeadline.minLines(true));
        equal(2, QuestionHeadline.minLines(false));
        equal(4, QuestionHeadline.maxLines(true));
        equal(6, QuestionHeadline.maxLines(false));

        equal("", QuestionHeadline.displayQuestion(null));
        equal("", QuestionHeadline.displayQuestion("   "));
        equal("What is RAM?", QuestionHeadline.displayQuestion("  what   is   RAM  "));
        equal("What is RAM?", QuestionHeadline.displayQuestion("What is RAM"));
        equal("What is RAM?", QuestionHeadline.displayQuestion("What is RAM?"));
        equal("What is RAM.", QuestionHeadline.displayQuestion("What is RAM."));
        equal("Go.", QuestionHeadline.displayQuestion("go."));
        equal("USB-C power delivery?", QuestionHeadline.displayQuestion("USB-C power delivery"));
        equal("In 60 words, why do GPUs help with AI?",
                QuestionHeadline.displayQuestion("In 60 words, why do GPUs help with AI?"));
        equal("You asked: What is RAM?",
                QuestionHeadline.formatHeadline("You asked: what is RAM", prefix));
        equal("You asked: What is RAM?",
                QuestionHeadline.formatHeadline("  what is RAM  ", prefix));
        equal("What is RAM?", QuestionHeadline.formatHeadline("what is RAM", ""));
        equal("You asked: ", QuestionHeadline.formatHeadline(null, prefix));
        equal("What is RAM?", QuestionHeadline.formatHeadline("what is RAM", null));

        equal(TypeConfig.header().size(false), QuestionHeadline.baseSp(false));
        equal(TypeConfig.header().size(true), QuestionHeadline.baseSp(true));
        equal(TypeConfig.body().size(false), QuestionHeadline.minSp(false));
        equal(TypeConfig.body().size(true), QuestionHeadline.minSp(true));
        equal(TypeConfig.subheader().size(false), QuestionHeadline.floorSp(false));
        equal(TypeConfig.subheader().size(true), QuestionHeadline.floorSp(true));
        equal(26, QuestionHeadline.shrinkSp(26, 11, 3, 6));
        equal(25, QuestionHeadline.shrinkSp(26, 11, 7, 6));
        equal(11, QuestionHeadline.shrinkSp(11, 11, 9, 6));
        System.out.println("QuestionHeadlineTest: OK");
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }

    private static void equal(String expected, String actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError(expected + " != " + actual);
        }
    }
}

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
        equal(3, QuestionHeadline.maxLines(true));
        equal(4, QuestionHeadline.maxLines(false));
        System.out.println("QuestionHeadlineTest: OK");
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

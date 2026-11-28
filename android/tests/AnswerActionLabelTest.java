package os.opos.launcher;

public final class AnswerActionLabelTest {
    public static void main(String[] args) {
        equal("this model", AnswerActionLabel.target(null));
        equal("this model", AnswerActionLabel.target(" \n "));
        equal("Nemotron 3.5 Bolt", AnswerActionLabel.target(" Nemotron 3.5 Bolt "));
        System.out.println("AnswerActionLabelTest: OK");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

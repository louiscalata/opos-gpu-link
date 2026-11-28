package os.opos.launcher;

import java.util.Arrays;
import java.util.Collections;

public final class AnswerOutcomeTest {
    public static void main(String[] args) {
        equal(AnswerOutcome.Result.NONE, AnswerOutcome.terminal(Collections.emptyList()));
        equal(AnswerOutcome.Result.NONE, AnswerOutcome.terminal(Arrays.asList("done", "answering")));
        equal(AnswerOutcome.Result.FINISHED, AnswerOutcome.terminal(Arrays.asList("done", "done")));
        equal(AnswerOutcome.Result.STOPPED, AnswerOutcome.terminal(Arrays.asList("done", "cancelled")));
        equal(AnswerOutcome.Result.FAILED, AnswerOutcome.terminal(Arrays.asList("failed", "cancelled")));
        equal(AnswerOutcome.Result.FINISHED,
                AnswerOutcome.visible(AnswerOutcome.Result.FINISHED, true));
        equal(AnswerOutcome.Result.NONE,
                AnswerOutcome.visible(AnswerOutcome.Result.FINISHED, false));
        equal(AnswerOutcome.Result.NONE,
                AnswerOutcome.visible(AnswerOutcome.Result.FAILED, false));
        System.out.println("AnswerOutcomeTest: OK");
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

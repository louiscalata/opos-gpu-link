package os.opos.launcher;

import java.util.Collection;

/** Names the outcome only after every requested answer has ended. */
final class AnswerOutcome {
    enum Result { NONE, FINISHED, STOPPED, FAILED }

    private AnswerOutcome() {}

    /** A connection change takes precedence over an old answer's end state. */
    static Result visible(Result outcome, boolean computerConnected) {
        return computerConnected ? outcome : Result.NONE;
    }

    static Result terminal(Collection<String> states) {
        if (states == null || states.isEmpty()) return Result.NONE;
        boolean failed = false;
        boolean stopped = false;
        for (String state : states) {
            if ("failed".equals(state)) failed = true;
            else if ("cancelled".equals(state)) stopped = true;
            else if (!"done".equals(state)) return Result.NONE;
        }
        return failed ? Result.FAILED : stopped ? Result.STOPPED : Result.FINISHED;
    }
}

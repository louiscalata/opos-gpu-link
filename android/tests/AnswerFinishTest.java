package os.opos.launcher;

public final class AnswerFinishTest {
    public static void main(String[] args) {
        // No service stamp (older phone service): the observed time, as before.
        equal(50_000L, AnswerFinish.elapsedAt(50_000L, 1_000_000L, 0L, 40_000L));
        // Seen 11 s late (Home right after Send): the real finish, 2.3 s after the ask.
        equal(42_300L, AnswerFinish.elapsedAt(53_300L, 1_011_000L, 1_000_000L, 40_000L));
        // Seen on the next 500 ms poll.
        equal(44_500L, AnswerFinish.elapsedAt(45_000L, 1_000_500L, 1_000_000L, 40_000L));
        // Stamp in the future (wall clock moved back): the observed time.
        equal(45_000L, AnswerFinish.elapsedAt(45_000L, 999_000L, 1_000_000L, 40_000L));
        // Stamp hours old (wall clock moved forward): the observed time.
        equal(45_000L, AnswerFinish.elapsedAt(45_000L,
                1_000_000L + AnswerFinish.MAX_LAG_MS + 1, 1_000_000L, 40_000L));
        // Stamp would land before the ask: the observed time, never a negative duration.
        equal(45_000L, AnswerFinish.elapsedAt(45_000L, 1_010_000L, 1_000_000L, 40_000L));
        System.out.println("AnswerFinishTest: OK");
    }

    private static void equal(long expected, long actual) {
        if (expected != actual) throw new AssertionError("Expected " + expected + " but was " + actual);
    }
}

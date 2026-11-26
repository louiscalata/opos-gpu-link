package os.opos.launcher;

/**
 * When a lane really finished, on the app's elapsedRealtime clock.
 *
 * The phone service stamps {@code ended_ms} (wall clock) once, when an answer
 * becomes done, failed or cancelled. The app only sees that on its next poll,
 * which can be seconds later after Home, the cover screen or screen off.
 */
final class AnswerFinish {
    /** Larger gaps than this are treated as a clock change, not a late poll. */
    static final long MAX_LAG_MS = 6L * 60L * 60L * 1000L;

    private AnswerFinish() {}

    static long elapsedAt(long nowElapsedMs, long nowWallMs, long endedWallMs,
                          long startedElapsedMs) {
        if (endedWallMs <= 0) return nowElapsedMs;
        long lag = nowWallMs - endedWallMs;
        if (lag < 0 || lag > MAX_LAG_MS) return nowElapsedMs;
        long finished = nowElapsedMs - lag;
        // A finish before the ask means the wall clock moved; keep the observed time.
        return finished < startedElapsedMs ? nowElapsedMs : finished;
    }
}

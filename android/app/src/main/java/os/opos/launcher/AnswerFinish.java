package os.opos.launcher;

/**
 * When a lane really finished, on the app's elapsedRealtime clock.
 *
 * The phone service stamps {@code ended_ms} (wall clock) once, when an answer
 * becomes done, failed or cancelled. The app only sees that on its next poll,
 * which can be seconds later after Home, the cover screen or screen off.
 * Both clocks are the phone's own: the service runs on the same device.
 */
final class AnswerFinish {
    /** Larger gaps than this are treated as a clock change, not a late poll. */
    static final long MAX_LAG_MS = 6L * 60L * 60L * 1000L;
    /** A finish this close before the recorded start is the ask round trip, not a clock jump. */
    static final long START_SLACK_MS = 5_000L;

    private AnswerFinish() {}

    static long elapsedAt(long nowElapsedMs, long nowWallMs, long endedWallMs,
                          long startedElapsedMs) {
        if (endedWallMs <= 0) return nowElapsedMs;
        long lag = nowWallMs - endedWallMs;
        if (lag < 0 || lag > MAX_LAG_MS) return nowElapsedMs;
        long finished = nowElapsedMs - lag;
        if (finished >= startedElapsedMs) return finished;
        // The start is recorded after the ask round trip, so a fast stop or failure can land
        // just before it. Further back means the wall clock moved; keep the observed time.
        return startedElapsedMs - finished <= START_SLACK_MS ? startedElapsedMs : nowElapsedMs;
    }
}

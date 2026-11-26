package os.opos.launcher;

/**
 * Stop appears where Send was the moment an ask starts, so the second tap of a double tap on
 * Send would stop the answers it just asked for. Ignore Stop taps that close to an ask.
 */
final class StopTapGuard {
    static final long GRACE_MS = 800L;
    /** Stop appearing this soon after an ask counts as appearing because of it. */
    static final long SHOWN_AFTER_ASK_MS = 10_000L;

    private StopTapGuard() {}

    static boolean ignore(long nowUptimeMs, long lastAskUptimeMs) {
        if (lastAskUptimeMs < 0) return false;
        long since = nowUptimeMs - lastAskUptimeMs;
        return since >= 0 && since < GRACE_MS;
    }
}

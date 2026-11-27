package os.opos.launcher;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * Decides, per lane, whether an answer is moving, stuck, paused, or over, and when one automatic
 * retry is due. Pure logic: the caller feeds it every fresh snapshot with a monotonic clock.
 *
 * A lane is "stuck" only on evidence: no new bytes for a long while while it claims to work, or a
 * PC lane that stays paused/queued although the cable is back. A phone-side lane waiting for its
 * turn is never stuck, because on-device models run one after another by design.
 */
final class LaneHealth {
    enum Status { IDLE, WORKING, STUCK, PAUSED, FAILED, CANCELLED, DONE }

    static final long STALL_ANSWERING_MS = 25_000;
    static final long STALL_LOADING_MS = 90_000;
    static final long PAUSED_WITH_CABLE_MS = 20_000;
    static final long PC_QUEUED_WITH_CABLE_MS = 30_000;
    /** An automatic retry waits this long beyond the point where the lane was called stuck. */
    static final long AUTO_AFTER_STUCK_MS = 30_000;
    static final long FAILED_AUTO_DELAY_MS = 3_000;

    static final class Verdict {
        final Status status;
        final boolean retryVisible;
        final boolean autoRetryDue;
        final boolean garbled;
        final String error;

        Verdict(Status status, boolean retryVisible, boolean autoRetryDue) {
            this(status, retryVisible, autoRetryDue, false, null);
        }

        Verdict(Status status, boolean retryVisible, boolean autoRetryDue,
                boolean garbled, String error) {
            this.status = status;
            this.retryVisible = retryVisible;
            this.autoRetryDue = autoRetryDue;
            this.garbled = garbled;
            this.error = error;
        }
    }

    private static final class Seen {
        final String id, state;
        final long size;
        final long changedAtMs;
        boolean garbled;

        Seen(String id, String state, long size, long changedAtMs) {
            this.id = id;
            this.state = state;
            this.size = size;
            this.changedAtMs = changedAtMs;
        }
    }

    private final Map<String, Seen> seen = new HashMap<>();
    private final Set<String> autoSpent = new HashSet<>();
    private Boolean lastCable;
    private long cableSinceMs;
    /** Readiness is per lane: each PC lane's companion worker comes back on its own. */
    private final Map<String, Boolean> lastReady = new HashMap<>();
    private final Map<String, Long> readySinceMs = new HashMap<>();

    /** Errors that a second try can plausibly fix. Others (too long, low memory) are left alone. */
    static boolean transientError(String error) {
        return "restart".equals(error) || "stream_error".equals(error)
                || "model_start".equals(error) || "worker_start".equals(error)
                || "garbled".equals(error);
    }

    void observeCable(Boolean cableConnected, long nowMs) {
        if (!java.util.Objects.equals(lastCable, cableConnected)) {
            cableSinceMs = nowMs;
        }
        lastCable = cableConnected;
    }

    Verdict observe(String pane, String id, String state, String error, long size,
                    String question, boolean laneReady, long nowMs) {
        return observe(pane, id, state, error, size, null, question, laneReady, nowMs);
    }

    Verdict observe(String pane, String id, String state, String error, long size,
                    String text, String question, boolean laneReady, long nowMs) {
        if (id == null || id.isEmpty() || state == null || state.isEmpty()) {
            seen.remove(pane);
            lastReady.remove(pane);
            readySinceMs.remove(pane);
            return new Verdict(Status.IDLE, false, false);
        }
        Seen previous = seen.get(pane);
        boolean wasGarbled = previous != null && previous.id.equals(id) && previous.garbled;
        if (previous == null || !previous.id.equals(id) || !previous.state.equals(state)
                || previous.size != size || nowMs < previous.changedAtMs) {
            previous = new Seen(id, state, size, nowMs);
            seen.put(pane, previous);
        }
        // Latch corruption to this answer ID: a moving tail must not turn a bad answer good.
        previous.garbled = wasGarbled || "garbled".equals(error) || AnswerGuard.reason(text) != null;
        long quiet = nowMs - previous.changedAtMs;
        boolean pc = PaneKeys.pc(pane);
        boolean cableBack = !Boolean.FALSE.equals(lastCable);
        // After a replug the PC needs its grace period counted from the replug, not from the pull.
        long cableQuiet = Math.min(quiet, Math.max(0, nowMs - cableSinceMs));
        String key = pane + "|" + (question == null ? "" : question);
        // Quiet time alone is not proof of a stall, so the automatic retry waits for a cable
        // that is known to be connected; an unknown cable only ever offers the manual button.
        boolean autoLeft = !autoSpent.contains(key) && laneReady
                && (!pc || Boolean.TRUE.equals(lastCable));
        Long readySince = readySinceMs.get(pane);
        if (readySince == null || !java.util.Objects.equals(lastReady.get(pane), laneReady)
                || nowMs < readySince) {
            readySince = nowMs;
            readySinceMs.put(pane, readySince);
        }
        lastReady.put(pane, laneReady);
        // Stuck grace for a paused lease starts when the cable is back AND the
        // companion is ready, so a ~50 s warmup does not already consume it.
        long readyQuiet = laneReady ? Math.max(0, nowMs - readySince) : 0;
        long graceQuiet = Math.min(cableQuiet, readyQuiet);
        // Stop wins over the garble latch: a cancelled answer must never be re-asked automatically.
        if ("cancelled".equals(state)) {
            return new Verdict(Status.CANCELLED, true, false);
        }
        if (previous.garbled) {
            return new Verdict(Status.FAILED, true, autoLeft, true, "garbled");
        }
        switch (state) {
            case "done":
                return new Verdict(Status.DONE, true, false);
            case "failed":
                return new Verdict(Status.FAILED, true,
                        autoLeft && transientError(error) && quiet >= FAILED_AUTO_DELAY_MS);
            case "paused":
                // Only a computer lane waits for the cable; a phone lane never depends on it.
                if (pc && !cableBack) return plannedPause();
                if (!pc) {
                    // A phone-side lane is only ever paused by a backend restart; treat as stuck at once.
                    return new Verdict(quiet >= PAUSED_WITH_CABLE_MS ? Status.STUCK : Status.WORKING,
                            quiet >= PAUSED_WITH_CABLE_MS, false);
                }
                // Warming after a replug: stay Paused without Retry, never auto-retry
                // a resumable lease (Retry would discard the saved partial).
                if (!laneReady) return warmingPause();
                return stuckVerdict(graceQuiet, PAUSED_WITH_CABLE_MS, false);
            case "queued":
            case "waiting":
                if (!pc) return new Verdict(Status.WORKING, false, false);
                if (!cableBack) return plannedPause();
                if (!laneReady) return warmingPause();
                return stuckVerdict(graceQuiet, PC_QUEUED_WITH_CABLE_MS, autoLeft);
            case "loading":
                if (pc && !cableBack) return plannedPause();
                if (pc && !laneReady) return warmingPause();
                // Grace counts from the replug AND readiness, so a long warmup does not turn the
                // first ready poll into STUCK and an automatic retry of a resuming answer.
                return stuckVerdict(pc ? graceQuiet : quiet, STALL_LOADING_MS, pc && autoLeft);
            case "answering":
                if (pc && !cableBack) return plannedPause();
                if (pc && !laneReady) return warmingPause();
                return stuckVerdict(pc ? graceQuiet : quiet, STALL_ANSWERING_MS, pc && autoLeft);
            default:
                return new Verdict(Status.WORKING, false, false);
        }
    }

    boolean garbled(String pane, String id) {
        Seen value = seen.get(pane);
        return value != null && value.id.equals(id) && value.garbled;
    }

    /** Cable out: the answer waits for the replug. No Retry, never automatic. */
    private static Verdict plannedPause() {
        return new Verdict(Status.PAUSED, false, false);
    }

    /**
     * Cable back, companion still warming: stay Paused with no Retry. A retry cannot run until
     * the lane is ready (the button would only show disabled), and once it is ready the normal
     * stuck grace, counted from readiness, offers Retry.
     */
    private static Verdict warmingPause() {
        return new Verdict(Status.PAUSED, false, false);
    }

    private static Verdict stuckVerdict(long quiet, long limit, boolean autoAllowed) {
        if (quiet < limit) return new Verdict(Status.WORKING, false, false);
        return new Verdict(Status.STUCK, true, autoAllowed && quiet >= limit + AUTO_AFTER_STUCK_MS);
    }

    /** One automatic retry per lane and question. A manual tap never spends it. */
    void markAutoRetried(String pane, String question) {
        autoSpent.add(pane + "|" + (question == null ? "" : question));
    }

    void markRetried(String pane) {
        seen.remove(pane);
    }

    void reset() {
        seen.clear();
        autoSpent.clear();
        lastCable = null;
        lastReady.clear();
        cableSinceMs = 0;
        readySinceMs.clear();
    }
}

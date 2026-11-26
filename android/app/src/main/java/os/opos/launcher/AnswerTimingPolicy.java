package os.opos.launcher;

import java.util.HashSet;
import java.util.Set;

/** Keeps pause-inclusive wall time out of model-speed figures for an answer ID. */
final class AnswerTimingPolicy {
    static final String DONE_UNMEASURED = "Done · time unmeasured";
    static final String WALL_WITH_PAUSE = "Wall elapsed · includes pause";
    static final String LEGACY_WALL = "Wall elapsed · pause history unknown";

    private final Set<String> interruptedIds = new HashSet<>();

    void observe(String pane, String state, String id, Boolean cableConnected) {
        if (id != null && !id.isEmpty()
                && PcPausePolicy.paused(pane, state, cableConnected)) {
            interruptedIds.add(id);
        }
    }

    boolean interrupted(String id) {
        return id != null && interruptedIds.contains(id);
    }

    void clear() { interruptedIds.clear(); }

    static Long modelDuration(Long wallDurationMs, boolean interrupted) {
        return interrupted ? null : wallDurationMs;
    }

    static Long comparisonFinish(Long finishedAtMs, boolean interrupted) {
        return interrupted ? null : finishedAtMs;
    }

    static long archivedDuration(Long wallDurationMs, boolean interrupted) {
        Long measured = modelDuration(wallDurationMs, interrupted);
        return measured == null ? -1 : measured;
    }

    static String doneLabel(Long wallDurationMs, boolean interrupted) {
        if (interrupted) return DONE_UNMEASURED;
        return wallDurationMs == null ? "Done"
                : "Done · " + NewspaperSummary.seconds(wallDurationMs);
    }

    static String rowMarker(String visibleState, boolean interrupted) {
        if (visibleState != null && visibleState.startsWith("Paused")) return "paused";
        return interrupted && visibleState != null && visibleState.startsWith("Done")
                ? "unmeasured" : null;
    }

    static String overallLabel(boolean pauseObserved) {
        return pauseObserved ? WALL_WITH_PAUSE : "";
    }

    static String legacyDoneLabel(String state, long wallDurationMs) {
        if (state == null || !state.startsWith("Done")) return state;
        return wallDurationMs < 0 ? "Done · time unmeasured (pause history unknown)"
                : "Done · " + NewspaperSummary.seconds(wallDurationMs)
                + " wall elapsed (pause history unknown)";
    }
}

package os.opos.launcher;

import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/** Measures model-active time by subtracting recorded pause intervals from wall time. */
final class AnswerTimingPolicy {
    static final String DONE_UNMEASURED = "Done · time unmeasured";
    static final String WALL_WITH_PAUSE = "Wall elapsed · includes pause";
    static final String LEGACY_WALL = "Wall elapsed · pause history unknown";

    private final Set<String> interruptedIds = new HashSet<>();
    private final Map<String, Long> pauseMs = new HashMap<>();
    private final Map<String, Long> pauseStartedAt = new HashMap<>();

    void observe(String pane, String state, String id, Boolean cableConnected, long nowMs) {
        if (id == null || id.isEmpty()) return;
        boolean paused = PcPausePolicy.paused(pane, state, cableConnected);
        if (paused) {
            interruptedIds.add(id);
            if (!pauseStartedAt.containsKey(id)) pauseStartedAt.put(id, nowMs);
            return;
        }
        Long started = pauseStartedAt.remove(id);
        if (started != null) {
            long added = Math.max(0, nowMs - started);
            pauseMs.put(id, pauseMs.getOrDefault(id, 0L) + added);
        }
    }

    boolean interrupted(String id) {
        return id != null && interruptedIds.contains(id);
    }

    boolean pauseMeasured(String id) {
        return id != null && (pauseMs.containsKey(id) || pauseStartedAt.containsKey(id));
    }

    long pauseMs(String id, long nowMs) {
        if (id == null) return 0;
        long total = pauseMs.getOrDefault(id, 0L);
        Long started = pauseStartedAt.get(id);
        if (started != null) total += Math.max(0, nowMs - started);
        return total;
    }

    Map<String, Long> pauseTotals() {
        return Collections.unmodifiableMap(pauseMs);
    }

    Map<String, Long> pauseStarts() {
        return Collections.unmodifiableMap(pauseStartedAt);
    }

    Set<String> interruptedAnswerIds() {
        return Collections.unmodifiableSet(interruptedIds);
    }

    void restore(Set<String> interrupted, Map<String, Long> totals, Map<String, Long> starts) {
        interruptedIds.clear();
        pauseMs.clear();
        pauseStartedAt.clear();
        if (interrupted != null) interruptedIds.addAll(interrupted);
        if (totals != null) {
            for (Map.Entry<String, Long> entry : totals.entrySet()) {
                if (entry.getKey() != null && !entry.getKey().isEmpty() && entry.getValue() != null) {
                    pauseMs.put(entry.getKey(), entry.getValue());
                }
            }
        }
        if (starts != null) {
            for (Map.Entry<String, Long> entry : starts.entrySet()) {
                if (entry.getKey() != null && !entry.getKey().isEmpty() && entry.getValue() != null) {
                    pauseStartedAt.put(entry.getKey(), entry.getValue());
                }
            }
        }
    }

    void clear() {
        interruptedIds.clear();
        pauseMs.clear();
        pauseStartedAt.clear();
    }

    static Long modelDuration(Long wallDurationMs, long pauseMs) {
        if (wallDurationMs == null) return null;
        return Math.max(0, wallDurationMs - Math.max(0, pauseMs));
    }

    static Long comparisonFinish(Long finishedAtMs) {
        return finishedAtMs;
    }

    static long archivedDuration(Long wallDurationMs, long pauseMs, boolean interrupted,
                                 boolean pauseMeasured) {
        Long measured = displayDuration(wallDurationMs, pauseMs, interrupted, pauseMeasured);
        return measured == null ? -1 : measured;
    }

    static Long displayDuration(Long wallDurationMs, long pauseMs, boolean interrupted,
                                boolean pauseMeasured) {
        if (interrupted && !pauseMeasured) return null;
        return modelDuration(wallDurationMs, pauseMs);
    }

    static String doneLabel(Long wallDurationMs, long pauseMs, boolean interrupted,
                            boolean pauseMeasured) {
        Long measured = displayDuration(wallDurationMs, pauseMs, interrupted, pauseMeasured);
        if (interrupted && !pauseMeasured) return DONE_UNMEASURED;
        return measured == null ? "Done"
                : "Done · " + NewspaperSummary.seconds(measured);
    }

    static String rowMarker(String visibleState, boolean interrupted, boolean pauseMeasured) {
        if (visibleState != null && visibleState.startsWith("Paused")) return "paused";
        if (interrupted && !pauseMeasured && visibleState != null && visibleState.startsWith("Done")) {
            return "unmeasured";
        }
        return null;
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

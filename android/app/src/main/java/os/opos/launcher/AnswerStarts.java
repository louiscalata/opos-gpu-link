package os.opos.launcher;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

/** Saved answer start stamps (SystemClock.elapsedRealtime) that survive an activity restart. */
final class AnswerStarts {
    private AnswerStarts() {}

    /**
     * Only stamps from this boot are usable: elapsedRealtime restarts at zero after a reboot.
     * The boot counter must match (a stale stamp can be smaller than the new uptime); the
     * {@code <= now} check is only a sanity bound. Unknown boot counts drop everything.
     */
    static Map<String, Long> sameBoot(Map<String, Long> saved, int savedBootCount,
                                      int currentBootCount, long nowElapsedMs) {
        Map<String, Long> kept = new HashMap<>();
        if (saved == null || savedBootCount < 0 || savedBootCount != currentBootCount) return kept;
        for (Map.Entry<String, Long> entry : saved.entrySet()) {
            Long value = entry.getValue();
            if (entry.getKey() != null && !entry.getKey().isEmpty()
                    && value != null && value > 0 && value <= nowElapsedMs) {
                kept.put(entry.getKey(), value);
            }
        }
        return kept;
    }

    /** Keep only the starts of the answers the current question is following (save and restore). */
    static Map<String, Long> onlyFollowed(Map<String, Long> starts, Collection<String> currentIds) {
        Map<String, Long> kept = new HashMap<>();
        if (starts == null || currentIds == null) return kept;
        for (Map.Entry<String, Long> entry : starts.entrySet()) {
            if (entry.getKey() != null && entry.getValue() != null
                    && currentIds.contains(entry.getKey())) {
                kept.put(entry.getKey(), entry.getValue());
            }
        }
        return kept;
    }
}

package os.opos.launcher;

import java.util.Collection;
import java.util.HashMap;
import java.util.Map;

/** Saved answer start stamps (SystemClock.elapsedRealtime) that survive an activity restart. */
final class AnswerStarts {
    private AnswerStarts() {}

    /** Only stamps from this boot are usable: elapsedRealtime restarts at zero after a reboot. */
    static Map<String, Long> sameBoot(Map<String, Long> saved, long nowElapsedMs) {
        Map<String, Long> kept = new HashMap<>();
        for (Map.Entry<String, Long> entry : saved.entrySet()) {
            Long value = entry.getValue();
            if (entry.getKey() != null && !entry.getKey().isEmpty()
                    && value != null && value > 0 && value <= nowElapsedMs) {
                kept.put(entry.getKey(), value);
            }
        }
        return kept;
    }

    /** Save only the starts of the answers the current question is following. */
    static Map<String, Long> toSave(Map<String, Long> starts, Collection<String> currentIds) {
        Map<String, Long> kept = new HashMap<>();
        for (Map.Entry<String, Long> entry : starts.entrySet()) {
            if (entry.getKey() != null && entry.getValue() != null
                    && currentIds.contains(entry.getKey())) {
                kept.put(entry.getKey(), entry.getValue());
            }
        }
        return kept;
    }
}

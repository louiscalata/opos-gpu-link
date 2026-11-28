package os.opos.launcher;

import java.util.Locale;
import java.util.List;

/** Local-only figures derived from the already displayed answer and elapsed time. */
final class NewspaperSummary {
    private NewspaperSummary() {}

    static int wordCount(String text) {
        if (text == null || text.isEmpty()) return 0;
        int words = 0;
        boolean hasLetterOrNumber = false;
        for (int index = 0; index < text.length(); index++) {
            char c = text.charAt(index);
            if (Character.isWhitespace(c)) {
                if (hasLetterOrNumber) words++;
                hasLetterOrNumber = false;
            } else if (Character.isLetterOrDigit(c)) {
                hasLetterOrNumber = true;
            }
        }
        return words + (hasLetterOrNumber ? 1 : 0);
    }

    static String seconds(long millis) {
        return String.format(Locale.US, "%.1f s", Math.max(0, millis) / 1000.0);
    }

    static String timing(Long pcMillis, Long phoneMillis) {
        String pc = pcMillis == null ? "PC …" : "PC " + seconds(pcMillis);
        String phone = phoneMillis == null ? "Phone …" : "Phone " + seconds(phoneMillis);
        return pc + " · " + phone;
    }

    static String line(String label, String answer, String state) {
        int count = wordCount(answer);
        return label + " · " + count + (count == 1 ? " word" : " words")
                + " · " + state;
    }

    static String finishedFirst(String pcState, Long pcMillis,
                                String phoneState, Long phoneMillis) {
        if (!pcState.startsWith("Done") || !phoneState.startsWith("Done")) return "";
        if (pcMillis == null || phoneMillis == null) return "Finish order unavailable";
        long difference = Math.abs(pcMillis - phoneMillis);
        if (difference < 50) return "Both finished together";
        return (pcMillis < phoneMillis ? "PC" : "Phone")
                + " finished first by " + seconds(difference);
    }

    static final class Lane {
        final String label;
        final String answer;
        final String state;
        final Long elapsedMs;
        final Long finishedAtMs;
        final boolean included;
        final int words;
        final boolean pending;
        final String timingMarker;
        /** The cable was pulled during this answer, so its finish time includes the pause. */
        final boolean includesPause;

        Lane(String label, String answer, String state, Long elapsedMs) {
            this(label, answer, state, elapsedMs, elapsedMs, true);
        }

        Lane(String label, String answer, String state, Long elapsedMs,
             boolean included) {
            this(label, answer, state, elapsedMs, elapsedMs, included);
        }

        Lane(String label, String answer, String state, Long elapsedMs,
             Long finishedAtMs, boolean included) {
            this(label, answer, state, elapsedMs, finishedAtMs,
                    included, wordCount(answer));
        }

        Lane(String label, String answer, String state, Long elapsedMs,
             Long finishedAtMs, boolean included, int words) {
            this(label, answer, state, elapsedMs, finishedAtMs, included, words,
                    included && elapsedMs == null && ("Thinking…".equals(state)
                    || "Streaming…".equals(state) || "Waiting for its turn…".equals(state)
                    || state.startsWith("Paused")));
        }

        Lane(String label, String answer, String state, Long elapsedMs,
             Long finishedAtMs, boolean included, int words, boolean pending) {
            this(label, answer, state, elapsedMs, finishedAtMs, included, words,
                    pending, null);
        }

        Lane(String label, String answer, String state, Long elapsedMs,
             Long finishedAtMs, boolean included, int words, boolean pending,
             String timingMarker) {
            this(label, answer, state, elapsedMs, finishedAtMs, included, words,
                    pending, timingMarker, false);
        }

        Lane(String label, String answer, String state, Long elapsedMs,
             Long finishedAtMs, boolean included, int words, boolean pending,
             String timingMarker, boolean includesPause) {
            this.includesPause = includesPause;
            this.label = label;
            this.answer = answer;
            this.state = state;
            this.elapsedMs = elapsedMs;
            this.finishedAtMs = finishedAtMs;
            this.included = included;
            this.words = words;
            this.pending = pending;
            this.timingMarker = timingMarker;
        }
    }

    static String timing(List<Lane> lanes) {
        StringBuilder result = new StringBuilder();
        for (Lane lane : lanes) {
            if (result.length() > 0) result.append('\n');
            result.append(timingRow(lane.label, lane.timingMarker != null ? lane.timingMarker
                    : lane.elapsedMs != null ? seconds(lane.elapsedMs)
                    : lane.pending ? pendingWord(lane.state) : "—"));
        }
        return result.toString();
    }

    /**
     * The TONIGHT value for a lane that has no time yet. It names what the lane card already
     * says, so a streaming lane never reads "waiting" next to a card that says "Streaming…".
     * Unknown states keep the old "waiting".
     */
    static String pendingWord(String state) {
        String lower = state == null ? "" : state.trim().toLowerCase(Locale.US);
        if (lower.startsWith("streaming")) return "streaming";
        if (lower.startsWith("thinking")) return "thinking";
        if (lower.startsWith("paused")) return "paused";
        if (lower.startsWith("retrying")) return "retrying";
        if (lower.startsWith("waiting for its turn") || lower.startsWith("queued")) return "queued";
        return "waiting";
    }

    static String timingRow(String label, String value) {
        return label + '\u00a0' + value.replace(' ', '\u00a0');
    }

    /** Old saved issues used two spaces between the lane label and value. */
    static String timingForDisplay(String saved) {
        String[] rows = saved.split("\\n", -1);
        for (int i = 0; i < rows.length; i++) {
            int separator = rows[i].lastIndexOf("  ");
            if (separator >= 0) {
                rows[i] = timingRow(rows[i].substring(0, separator),
                        rows[i].substring(separator + 2));
            }
        }
        return String.join("\n", rows);
    }

    /**
     * Question total: the latest finish stamp among the included lanes minus the question's
     * start stamp (both SystemClock.elapsedRealtime). Null if the start is unknown or any
     * included lane has no finish stamp, so the caller falls back to its own clock.
     */
    static Long totalFromFinishes(List<Lane> lanes, long questionStartedAtMs) {
        if (questionStartedAtMs <= 0) return null;
        Long latest = null;
        for (Lane lane : lanes) {
            if (!lane.included) continue;
            if (lane.finishedAtMs == null) return null;
            if (latest == null || lane.finishedAtMs > latest) latest = lane.finishedAtMs;
        }
        return latest == null ? null : Math.max(0, latest - questionStartedAtMs);
    }

    /**
     * Fail closed: a lane is settled only when the caller does not flag it pending and its
     * state is a known end (Done, or an error line such as a stop or failure). Anything
     * else ("Loading…", "Retrying… (2/3)", "Queued", "Paused — …") is still going.
     */
    static boolean stillGoing(Lane lane) {
        if (lane.pending) return true;
        String state = lane.state == null ? "" : lane.state.trim();
        if (state.startsWith("Done")) return false;
        if (state.startsWith("Stopped")) return false;
        if (state.toLowerCase(Locale.US).contains("paused")) return true;
        return !ErrorCopy.errorLine(state);
    }

    static String report(List<Lane> lanes) {
        StringBuilder result = new StringBuilder();
        Lane fastest = null;
        Lane slowest = null;
        Lane longest = null;
        Lane first = null;
        Lane second = null;
        boolean allDone = true;
        boolean anyPending = false;
        boolean anyIncluded = false;
        int includedCount = 0;
        for (Lane lane : lanes) {
            if (result.length() > 0) result.append('\n');
            result.append(lane.label).append(" · ").append(lane.words)
                    .append(lane.words == 1 ? " word" : " words")
                    .append(" · ").append(lane.state);
            if (!lane.included) continue;
            anyIncluded = true;
            includedCount++;
            if (!lane.state.startsWith("Done")) allDone = false;
            if (stillGoing(lane)) anyPending = true;
            if (lane.elapsedMs != null && lane.state.startsWith("Done")) {
                if (fastest == null || lane.elapsedMs < fastest.elapsedMs) fastest = lane;
                if (slowest == null || lane.elapsedMs >= slowest.elapsedMs) slowest = lane;
            }
            if (lane.finishedAtMs != null && lane.state.startsWith("Done")) {
                if (first == null || lane.finishedAtMs < first.finishedAtMs) {
                    second = first;
                    first = lane;
                } else if (second == null || lane.finishedAtMs < second.finishedAtMs) {
                    second = lane;
                }
            }
            if (longest == null || lane.words > longest.words) {
                longest = lane;
            }
        }
        allDone &= anyIncluded;
        // "so far" promises more results; a Stop or a failed lane ends the question too.
        boolean settled = anyIncluded && !anyPending;
        if (fastest != null) {
            result.append('\n').append(settled ? "Fastest: " : "Fastest so far: ")
                    .append(fastest.label).append(" (" + seconds(fastest.elapsedMs) + ")");
            // One measured lane is not a range: "Fastest: Phone · Slowest: Phone" reads as a bug.
            if (slowest != fastest) {
                result.append(" · ").append(settled ? "Slowest: " : "Slowest so far: ")
                        .append(slowest.label).append(" (" + seconds(slowest.elapsedMs) + ")");
            }
        }
        if (longest != null) result.append('\n')
                .append(settled ? "Longest answer: " : "Longest answer so far: ")
                .append(longest.label).append(" (" + longest.words + " words)");
        if (first != null && second != null) {
            long margin = Math.max(0, second.finishedAtMs - first.finishedAtMs);
            result.append('\n');
            // Same 50 ms tie rule as finishedFirst(): never "finished first by 0.0 s".
            if (margin < 50) {
                result.append(first.label).append(" and ").append(second.label)
                        .append(" finished together");
            } else {
                result.append(first.label).append(" finished first by ").append(seconds(margin));
            }
            // The margin is wall time; after a cable pull it must say so.
            if (first.includesPause || second.includesPause) result.append(" · includes pause");
        }
        else if (allDone && includedCount >= 2) {
            result.append('\n').append("Finish order unavailable");
        }
        return result.toString();
    }
}

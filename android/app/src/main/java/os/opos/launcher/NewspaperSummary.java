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
                    : lane.pending ? "waiting" : "—"));
        }
        return result.toString();
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

    static String report(List<Lane> lanes) {
        StringBuilder result = new StringBuilder();
        Lane fastest = null;
        Lane slowest = null;
        Lane longest = null;
        Lane first = null;
        Lane second = null;
        boolean allDone = true;
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
            if (lane.elapsedMs != null && lane.state.startsWith("Done")) {
                if (fastest == null || lane.elapsedMs < fastest.elapsedMs) fastest = lane;
                if (slowest == null || lane.elapsedMs > slowest.elapsedMs) slowest = lane;
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
        if (fastest != null) {
            result.append('\n').append(allDone ? "Fastest: " : "Fastest so far: ")
                    .append(fastest.label).append(" (" + seconds(fastest.elapsedMs) + ")");
            // One measured lane is not a range: "Fastest: Phone · Slowest: Phone" reads as a bug.
            if (slowest != fastest) {
                result.append(" · ").append(allDone ? "Slowest: " : "Slowest so far: ")
                        .append(slowest.label).append(" (" + seconds(slowest.elapsedMs) + ")");
            }
        }
        if (longest != null) result.append('\n')
                .append(allDone ? "Longest answer: " : "Longest answer so far: ")
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
        }
        else if (allDone && includedCount >= 2) {
            result.append('\n').append("Finish order unavailable");
        }
        return result.toString();
    }
}

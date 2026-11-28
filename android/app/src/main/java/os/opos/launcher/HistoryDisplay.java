package os.opos.launcher;

import java.util.List;

/** Names saved answers consistently without changing the archived record. */
final class HistoryDisplay {
    private HistoryDisplay() {}

    static String label(HistoryStore.Lane lane) {
        if (lane == null) return "";
        String name = lane.label.trim();
        if ("phone".equals(lane.pane) && "This phone".equalsIgnoreCase(name)) {
            name = legacyPhoneModel(lane.maker);
        }
        if (name.isEmpty()) name = PaneKeys.fallbackLabel(lane.pane);
        name = ModelDisplay.label(name);
        return PaneKeys.pc(lane.pane)
                ? ComputerWords.apply(name, PaneKeys.archivedComputer(lane.where)) : name;
    }

    /** Old lead-phone saves put "Model · Maker" in the maker field. */
    static String maker(HistoryStore.Lane lane) {
        String maker = lane.maker.trim();
        if ("phone".equals(lane.pane) && "This phone".equalsIgnoreCase(lane.label.trim())
                && !legacyPhoneModel(maker).isEmpty()) {
            int divider = maker.indexOf(" · ");
            return divider < 0 ? "" : maker.substring(divider + 3).trim();
        }
        return maker;
    }

    static String timing(HistoryStore.Issue issue) {
        String noun = ComputerWords.COMPUTER;
        for (HistoryStore.Lane lane : issue.lanes) {
            if (!PaneKeys.pc(lane.pane)) continue;
            String savedNoun = PaneKeys.archivedComputer(lane.where);
            if (!ComputerWords.COMPUTER.equals(savedNoun)) {
                noun = savedNoun;
                break;
            }
        }
        String[] rows = issue.timing.split("\\n", -1);
        for (int i = 0; i < rows.length; i++) {
            // Older issues can put two timings on one line, separated by a middle dot.
            String[] segments = rows[i].split(" · ", -1);
            for (int j = 0; j < segments.length; j++) {
                segments[j] = timingSegment(segments[j], issue.lanes);
            }
            rows[i] = String.join(" · ", segments);
        }
        return ComputerWords.apply(String.join("\n", rows), noun);
    }

    private static String timingSegment(String segment, List<HistoryStore.Lane> lanes) {
        for (HistoryStore.Lane lane : lanes) {
            String suffix = timingSuffix(segment, lane.label);
            if (suffix == null) suffix = timingSuffix(segment, lane.label.trim());
            if (suffix != null) return label(lane) + suffix;
        }
        // The oldest timing rows said only "PC" or "Phone" even when their cards
        // saved a model name. These aliases identify the original lead lanes.
        for (HistoryStore.Lane lane : lanes) {
            String alias = "gpu".equals(lane.pane) ? "PC"
                    : "phone".equals(lane.pane) ? "Phone" : "";
            String suffix = timingSuffix(segment, alias);
            if (suffix != null) return label(lane) + suffix;
        }
        return segment;
    }

    private static String timingSuffix(String segment, String prefix) {
        if (prefix.isEmpty() || !segment.startsWith(prefix)) return null;
        String suffix = segment.substring(prefix.length());
        if (suffix.startsWith("\u00a0") || suffix.startsWith("  ")) return suffix;
        if (!suffix.startsWith(" ") || suffix.length() < 2) return null;
        // One-space rows predate the aligned timing list. A model name after
        // "PC" or "Phone" must not be mistaken for a timing value.
        String value = suffix.substring(1);
        if (Character.isDigit(value.charAt(0)) || value.startsWith("…") || value.startsWith("—")) {
            return suffix;
        }
        for (String state : new String[]{"failed", "unmeasured", "waiting", "streaming",
                "thinking", "paused", "retrying", "queued"}) {
            if (value.equals(state)) return suffix;
        }
        return null;
    }

    private static String legacyPhoneModel(String maker) {
        String value = maker == null ? "" : maker.trim();
        int divider = value.indexOf(" · ");
        if (divider > 0) return value.substring(0, divider).trim();
        // A model with no known maker was saved on its own; a maker-only value is not a model.
        return value.matches(".*\\d.*") ? value : "";
    }
}

package os.opos.launcher;

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
            for (HistoryStore.Lane lane : issue.lanes) {
                String savedLabel = lane.label;
                if (savedLabel.trim().isEmpty()) continue;
                if (rows[i].startsWith(savedLabel + '\u00a0')
                        || rows[i].startsWith(savedLabel + "  ")) {
                    rows[i] = label(lane) + rows[i].substring(savedLabel.length());
                    break;
                }
            }
        }
        return ComputerWords.apply(String.join("\n", rows), noun);
    }

    private static String legacyPhoneModel(String maker) {
        String value = maker == null ? "" : maker.trim();
        int divider = value.indexOf(" · ");
        if (divider > 0) return value.substring(0, divider).trim();
        // A model with no known maker was saved on its own; a maker-only value is not a model.
        return value.matches(".*\\d.*") ? value : "";
    }
}

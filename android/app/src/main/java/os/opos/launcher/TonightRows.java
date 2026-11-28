package os.opos.launcher;

import java.util.ArrayList;
import java.util.List;

/**
 * Splits the TONIGHT timing text ("PC\u00a03.3\u00a0s" per line) into a label column and
 * a value column, so the card can show an aligned two-column list with tabular numbers.
 */
final class TonightRows {
    private static final char NBSP = '\u00a0';

    private TonightRows() {}

    static final class Row {
        final String label;
        final String value;

        Row(String label, String value) {
            this.label = label;
            this.value = value;
        }

        /** A line with no value is a note and spans the whole card. */
        boolean note() {
            return value.isEmpty();
        }
    }

    static List<Row> parse(String timing) {
        List<Row> rows = new ArrayList<>();
        if (timing == null || timing.trim().isEmpty()) return rows;
        for (String line : timing.split("\\n", -1)) {
            if (line.trim().isEmpty()) continue;
            rows.add(parseLine(NewspaperSummary.timingForDisplay(line)));
        }
        return rows;
    }

    /** Timing writes one row per lane, in pane order; note rows have no lane. */
    static List<NewspaperSummary.Lane> matchingLanes(List<Row> rows,
                                                     List<NewspaperSummary.Lane> lanes) {
        List<NewspaperSummary.Lane> matches = new ArrayList<>();
        int laneIndex = 0;
        for (Row row : rows) {
            if (row.note()) {
                matches.add(null);
                continue;
            }
            matches.add(lanes != null && laneIndex < lanes.size() ? lanes.get(laneIndex) : null);
            laneIndex++;
        }
        return matches;
    }

    private static Row parseLine(String line) {
        String[] tokens = line.split(String.valueOf(NBSP), -1);
        if (tokens.length < 2) return new Row(line.trim(), "");
        int valueTokens = tokens.length >= 3 && "s".equals(tokens[tokens.length - 1])
                && isNumber(tokens[tokens.length - 2]) ? 2 : 1;
        StringBuilder label = new StringBuilder();
        for (int i = 0; i < tokens.length - valueTokens; i++) {
            if (i > 0) label.append(' ');
            label.append(tokens[i]);
        }
        StringBuilder value = new StringBuilder();
        for (int i = tokens.length - valueTokens; i < tokens.length; i++) {
            if (value.length() > 0) value.append(NBSP);
            value.append(tokens[i]);
        }
        return new Row(label.toString().trim(), value.toString());
    }

    private static boolean isNumber(String token) {
        if (token.isEmpty()) return false;
        boolean dot = false;
        for (int i = 0; i < token.length(); i++) {
            char c = token.charAt(i);
            if (c == '.' && !dot && i > 0) dot = true;
            else if (c < '0' || c > '9') return false;
        }
        return true;
    }
}

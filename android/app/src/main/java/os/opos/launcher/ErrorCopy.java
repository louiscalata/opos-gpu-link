package os.opos.launcher;

import java.util.ArrayList;
import java.util.List;

/**
 * Line-level error ranges for Summary and TONIGHT copy. A mixed block (one failed
 * lane and several Done lanes) must not be painted a single colour.
 */
final class ErrorCopy {
    static final class Range {
        final int start;
        final int end;
        final boolean error;

        Range(int start, int end, boolean error) {
            this.start = start;
            this.end = end;
            this.error = error;
        }
    }

    private ErrorCopy() {}

    static boolean errorLine(String line) {
        return UiPalette.tone(line) == UiPalette.Tone.ERROR;
    }

    static List<Range> lineRanges(String text) {
        List<Range> ranges = new ArrayList<>();
        if (text == null || text.isEmpty()) return ranges;
        int start = 0;
        for (int i = 0; i <= text.length(); i++) {
            if (i == text.length() || text.charAt(i) == '\n') {
                String line = text.substring(start, i);
                if (!line.isEmpty()) {
                    ranges.add(new Range(start, i, errorLine(line)));
                }
                start = i + 1;
            }
        }
        return ranges;
    }
}

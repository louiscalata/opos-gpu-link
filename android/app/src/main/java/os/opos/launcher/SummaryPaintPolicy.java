package os.opos.launcher;

import java.util.Objects;

/** Keep an open, selectable summary still until its words or colors change. */
final class SummaryPaintPolicy {
    private SummaryPaintPolicy() {}

    static final class Paint {
        final String report;
        final int ink;
        final int error;

        Paint(String report, int ink, int error) {
            this.report = report;
            this.ink = ink;
            this.error = error;
        }
    }

    static boolean needsPaint(Paint previous, String report, int ink, int error) {
        return previous == null || !Objects.equals(previous.report, report)
                || previous.ink != ink || previous.error != error;
    }
}

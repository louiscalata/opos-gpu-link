package os.opos.launcher;

import java.util.Objects;

/** Keep an open, selectable summary still until its words or colors change. */
final class SummaryPaintPolicy {
    private SummaryPaintPolicy() {}

    static final class Paint {
        final String report;
        final int ink;
        final int error;
        final int bodySp;

        Paint(String report, int ink, int error, int bodySp) {
            this.report = report;
            this.ink = ink;
            this.error = error;
            this.bodySp = bodySp;
        }
    }

    static boolean needsPaint(Paint previous, String report, int ink, int error, int bodySp) {
        return previous == null || !Objects.equals(previous.report, report)
                || previous.ink != ink || previous.error != error || previous.bodySp != bodySp;
    }
}

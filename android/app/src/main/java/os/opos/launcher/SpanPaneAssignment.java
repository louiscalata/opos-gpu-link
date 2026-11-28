package os.opos.launcher;

/**
 * Span pane assignment rules.
 */
final class SpanPaneAssignment {
    enum Pane {
        LEFT,
        RIGHT
    }

    enum Section {
        MASTHEAD,
        ANSWERS,
        COMPOSER,
        STATS,
        HEAT,
        WORKING
    }

    private SpanPaneAssignment() {
    }

    static Pane paneFor(Section s, SpanPolicy.Mode mode) {
        if (mode == SpanPolicy.Mode.SIDE_BY_SIDE) {
            switch (s) {
                case STATS:
                case HEAT:
                case WORKING:
                    return Pane.RIGHT;
                case MASTHEAD:
                case ANSWERS:
                case COMPOSER:
                default:
                    return Pane.LEFT;
            }
        }
        return Pane.LEFT;
    }
}

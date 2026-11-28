package os.opos.launcher;

/** Per-pane span metrics. */
final class SpanPaneMetrics {
    public final int leftWidthPx;
    public final int gutterPx;
    public final int rightWidthPx;

    private SpanPaneMetrics(int leftWidthPx, int gutterPx, int rightWidthPx) {
        this.leftWidthPx = leftWidthPx;
        this.gutterPx = gutterPx;
        this.rightWidthPx = rightWidthPx;
    }

    static SpanPaneMetrics from(SpanGeometry g) {
        if (!SpanPolicy.verticalHinge(g)) {
            return new SpanPaneMetrics(g == null ? 0 : g.windowW, 0, 0);
        }
        return new SpanPaneMetrics(g.hingeLeft, g.hingeRight - g.hingeLeft, g.windowW - g.hingeRight);
    }

    int leftWidthDp(int densityDpi) {
        return SpanPolicy.pxToDp(leftWidthPx, densityDpi);
    }

    int rightWidthDp(int densityDpi) {
        return SpanPolicy.pxToDp(rightWidthPx, densityDpi);
    }

    int gutterDp(int densityDpi) {
        return SpanPolicy.pxToDp(gutterPx, densityDpi);
    }
}

package os.opos.launcher;

public final class SpanPaneMetricsTest {
    public static void main(String[] args) {
        SpanGeometry duo1 = SpanGeometry.of(2784, 1800, 1350, 0, 1434, 1800);
        SpanPaneMetrics metrics = SpanPaneMetrics.from(duo1);
        equal(1350, metrics.leftWidthPx);
        equal(84, metrics.gutterPx);
        equal(1350, metrics.rightWidthPx);
        equal(539, metrics.leftWidthDp(401));
        equal(34, metrics.gutterDp(401));
        equal(539, metrics.rightWidthDp(401));

        SpanGeometry noHinge = SpanGeometry.NONE;
        SpanPaneMetrics none = SpanPaneMetrics.from(noHinge);
        equal(0, none.leftWidthPx);
        equal(0, none.gutterPx);
        equal(0, none.rightWidthPx);

        SpanGeometry fullWindow = SpanGeometry.of(2784, 1800, 0, 0, 0, 0);
        SpanPaneMetrics full = SpanPaneMetrics.from(fullWindow);
        equal(2784, full.leftWidthPx);
        equal(0, full.gutterPx);
        equal(0, full.rightWidthPx);

        check(metrics.leftWidthDp(0) == 0);
        check(metrics.gutterDp(0) == 0);
        check(metrics.rightWidthDp(0) == 0);

        SpanPaneMetrics beyond = SpanPaneMetrics.from(SpanGeometry.of(1000, 800, 400, 0, 1200, 800));
        equal(1000, beyond.leftWidthPx);
        equal(0, beyond.rightWidthPx);
        SpanPaneMetrics horizontal = SpanPaneMetrics.from(SpanGeometry.of(2784, 1800, 100, 500, 2600, 600));
        equal(2784, horizontal.leftWidthPx);
        equal(0, horizontal.gutterPx);

        System.out.println("SpanPaneMetricsTest: OK");
    }

    private static void check(boolean value) {
        if (!value) {
            throw new AssertionError();
        }
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) {
            throw new AssertionError(expected + " != " + actual);
        }
    }
}

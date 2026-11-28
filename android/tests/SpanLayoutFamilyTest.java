package os.opos.launcher;

/**
 * Pins that spanning the Surface Duo across both screens keeps the same layout family as one
 * screen, so CoverScreenPolicy.needsRecreate stays false on span and unspan.
 */
public final class SpanLayoutFamilyTest {
    public static void main(String[] args) {
        int dpi = 401;
        SpanGeometry spanned = SpanGeometry.of(2784, 1800, 1350, 0, 1434, 1800);
        // Window heights below are illustrative dp values for the usable height, not measurements.
        for (int heightDp : new int[] {640, 690, 699, 700, 718}) {
            int singleWidthDp = SpanPolicy.pxToDp(1350, dpi);
            int spannedWindowDp = SpanPolicy.pxToDp(2784, dpi);
            equal(539, singleWidthDp);
            equal(1111, spannedWindowDp);
            int content = SpanPolicy.contentWidthDp(spanned, dpi, spannedWindowDp);
            equal(singleWidthDp, content);
            CoverScreenPolicy.Mode single = CoverScreenPolicy.select(singleWidthDp, heightDp, 0);
            CoverScreenPolicy.Mode span = CoverScreenPolicy.select(content, heightDp, 0);
            check(single == span);
            check(!CoverScreenPolicy.needsRecreate(single, span));
        }
        // Without a hinge the window width passes through unchanged.
        equal(1111, SpanPolicy.contentWidthDp(SpanGeometry.NONE, dpi, 1111));
        equal(540, SpanPolicy.contentWidthDp(null, dpi, 540));
        // A horizontal or too-narrow hinge also passes the window width through.
        equal(1111, SpanPolicy.contentWidthDp(SpanGeometry.of(2784, 1800, 100, 500, 2600, 600), dpi, 1111));
        // Documents why the content width matters: the full spanned window is a different family.
        check(CoverScreenPolicy.select(1111, 690, 0) != CoverScreenPolicy.select(539, 690, 0));
        System.out.println("SpanLayoutFamilyTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

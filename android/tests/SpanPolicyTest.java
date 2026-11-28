package os.opos.launcher;

public final class SpanPolicyTest {
    public static void main(String[] args) {
        SpanGeometry duo1 = SpanGeometry.of(2784, 1800, 1350, 0, 1434, 1800);
        equal(SpanPolicy.Mode.SIDE_BY_SIDE.ordinal(), SpanPolicy.resolve(duo1, 401).ordinal());
        equal(539, SpanPolicy.pxToDp(1350, 401));
        equal(539, SpanPolicy.pxToDp(1351, 401));
        equal(0, SpanPolicy.pxToDp(10, 0));

        int minPanePx = 801; // 320 dp at 401 dpi is exactly 802 px, so 801 is one pixel under.
        SpanGeometry under = SpanGeometry.of(minPanePx + 84 + minPanePx, 1800, minPanePx, 0, minPanePx + 84, 1800);
        check(SpanPolicy.resolve(under, 401) == SpanPolicy.Mode.NONE);

        int atMinPanePx = 802;
        SpanGeometry atMin = SpanGeometry.of(atMinPanePx + 84 + atMinPanePx, 1800, atMinPanePx, 0, atMinPanePx + 84, 1800);
        check(SpanPolicy.resolve(atMin, 401) == SpanPolicy.Mode.SIDE_BY_SIDE);

        SpanGeometry horizontal = SpanGeometry.of(2784, 1800, 100, 500, 2600, 600);
        check(SpanPolicy.resolve(horizontal, 401) == SpanPolicy.Mode.NONE);

        SpanGeometry notCrossingTop = SpanGeometry.of(2784, 1800, 1350, 10, 1434, 1800);
        check(SpanPolicy.resolve(notCrossingTop, 401) == SpanPolicy.Mode.NONE);

        SpanGeometry notCrossingBottom = SpanGeometry.of(2784, 1800, 1350, 0, 1434, 1799);
        check(SpanPolicy.resolve(notCrossingBottom, 401) == SpanPolicy.Mode.NONE);

        SpanGeometry noHinge = SpanGeometry.NONE;
        check(SpanPolicy.resolve(noHinge, 401) == SpanPolicy.Mode.NONE);

        SpanGeometry zeroDensity = SpanGeometry.of(2784, 1800, 1350, 0, 1434, 1800);
        check(SpanPolicy.resolve(zeroDensity, 0) == SpanPolicy.Mode.NONE);

        SpanGeometry leftTooSmall = SpanGeometry.of(2784, 1800, 800, 0, 884, 1800);
        check(SpanPolicy.resolve(leftTooSmall, 401) == SpanPolicy.Mode.NONE);

        check(SpanPolicy.resolve(SpanGeometry.of(2784, 0, 1350, 0, 1434, 1), 401) == SpanPolicy.Mode.NONE);
        check(SpanPolicy.resolve(SpanGeometry.of(0, 1800, 1350, 0, 1434, 1800), 401) == SpanPolicy.Mode.NONE);
        check(SpanPolicy.resolve(SpanGeometry.of(1000, 800, 400, 0, 1200, 800), 401) == SpanPolicy.Mode.NONE);
        equal(13_421_773, SpanPolicy.pxToDp(13_421_773, 160));

        System.out.println("SpanPolicyTest: OK");
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

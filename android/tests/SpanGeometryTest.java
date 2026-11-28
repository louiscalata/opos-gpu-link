package os.opos.launcher;

public final class SpanGeometryTest {
    public static void main(String[] args) {
        SpanGeometry none = SpanGeometry.NONE;
        check(!none.hasHinge());
        equal(0, none.windowW);
        equal(0, none.windowH);
        equal(0, none.hingeLeft);
        equal(0, none.hingeTop);
        equal(0, none.hingeRight);
        equal(0, none.hingeBottom);

        SpanGeometry a = SpanGeometry.of(2784, 1800, 1350, 0, 1434, 1800);
        SpanGeometry b = SpanGeometry.of(2784, 1800, 1350, 0, 1434, 1800);
        SpanGeometry c = SpanGeometry.of(2784, 1800, 1351, 0, 1434, 1800);
        check(a.hasHinge());
        check(a.equals(b));
        check(a.hashCode() == b.hashCode());
        check(!a.equals(c));
        check(a.toString().contains("windowW=2784"));
        check(a.toString().contains("hingeRight=1434"));

        SpanGeometry horizontal = SpanGeometry.of(2784, 1800, 100, 500, 2600, 600);
        check(horizontal.hasHinge());

        SpanGeometry line = SpanGeometry.of(2784, 1800, 100, 0, 2600, 0);
        check(!line.hasHinge());

        System.out.println("SpanGeometryTest: OK");
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

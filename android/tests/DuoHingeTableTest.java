package os.opos.launcher;

/**
 * Tests for DuoHingeTable.
 */
public final class DuoHingeTableTest {
    public static void main(String[] args) {
        SpanGeometry duo1 = DuoHingeTable.geometry("Microsoft", "Surface Duo", 2784, 1800);
        equal(2784, duo1.windowW);
        equal(1800, duo1.windowH);
        equal(1350, duo1.hingeLeft);
        equal(0, duo1.hingeTop);
        equal(1434, duo1.hingeRight);
        equal(1800, duo1.hingeBottom);
        check(duo1.hasHinge());

        SpanGeometry duo1Trimmed = DuoHingeTable.geometry("  microsoft  ", "  surface duo  ", 2784, 1800);
        equal(1350, duo1Trimmed.hingeLeft);
        equal(1434, duo1Trimmed.hingeRight);

        SpanGeometry duo2 = DuoHingeTable.geometry("MICROSOFT", "Surface Duo 2", 2754, 1892);
        equal(2754, duo2.windowW);
        equal(1892, duo2.windowH);
        equal(1344, duo2.hingeLeft);
        equal(0, duo2.hingeTop);
        equal(1410, duo2.hingeRight);
        equal(1892, duo2.hingeBottom);
        check(duo2.hasHinge());

        SpanGeometry wrongSize = DuoHingeTable.geometry("Microsoft", "Surface Duo", 2783, 1800);
        check(!wrongSize.hasHinge());
        equal(SpanGeometry.NONE.windowW, wrongSize.windowW);
        equal(SpanGeometry.NONE.windowH, wrongSize.windowH);
        equal(SpanGeometry.NONE.hingeLeft, wrongSize.hingeLeft);
        equal(SpanGeometry.NONE.hingeTop, wrongSize.hingeTop);
        equal(SpanGeometry.NONE.hingeRight, wrongSize.hingeRight);
        equal(SpanGeometry.NONE.hingeBottom, wrongSize.hingeBottom);

        SpanGeometry unknownDevice = DuoHingeTable.geometry("Microsoft", "Other", 2784, 1800);
        check(!unknownDevice.hasHinge());

        SpanGeometry nullManufacturer = DuoHingeTable.geometry(null, "Surface Duo", 2784, 1800);
        check(!nullManufacturer.hasHinge());

        SpanGeometry nullModel = DuoHingeTable.geometry("Microsoft", null, 2784, 1800);
        check(!nullModel.hasHinge());

        SpanGeometry nonMicrosoft = DuoHingeTable.geometry("Google", "Surface Duo", 2784, 1800);
        check(!nonMicrosoft.hasHinge());

        java.util.Locale saved = java.util.Locale.getDefault();
        try {
            java.util.Locale.setDefault(java.util.Locale.forLanguageTag("tr-TR"));
            check(DuoHingeTable.geometry("MICROSOFT", "SURFACE DUO 2", 2754, 1892).hasHinge());
        } finally {
            java.util.Locale.setDefault(saved);
        }

        System.out.println("DuoHingeTableTest: OK");
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

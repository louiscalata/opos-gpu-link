package os.opos.launcher;

public final class LineSnapTest {
    public static void main(String[] args) {
        equal(120, LineSnap.viewportFor(137, 24));
        equal(0, LineSnap.viewportFor(23, 24));
        equal(0, LineSnap.viewportFor(-5, 24));
        equal(24, LineSnap.snapTop(47, new int[]{0, 24, 49, 73}));
        equal(49, LineSnap.snapTop(72, new int[]{0, 24, 49, 73}));
        equal(73, LineSnap.snapTop(1000, new int[]{0, 24, 49, 73}));
        equal(0, LineSnap.snapTop(-1, new int[]{0, 24}));
        equal(0, LineSnap.snapTop(20, new int[0]));
        try {
            LineSnap.viewportFor(100, 0);
            throw new AssertionError("Expected invalid line height");
        } catch (IllegalArgumentException expected) {
            // Zero line height cannot define a viewport.
        }
        System.out.println("LineSnapTest: OK");
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

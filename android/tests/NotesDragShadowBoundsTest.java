package os.opos.launcher;

public final class NotesDragShadowBoundsTest {
    public static void main(String[] args) {
        equal(480, NotesDragShadowBounds.MAX_WIDTH_DP);
        equal(160, NotesDragShadowBounds.MAX_HEIGHT_DP);
        equal(320, NotesDragShadowBounds.pixels(320, 480));
        equal(480, NotesDragShadowBounds.pixels(1200, 480));
        equal(160, NotesDragShadowBounds.pixels(100_000, 160));
        equal(1, NotesDragShadowBounds.pixels(0, 160));
        equal(1, NotesDragShadowBounds.pixels(-1, 160));
        equal(1, NotesDragShadowBounds.pixels(320, 0));
        System.out.println("NotesDragShadowBoundsTest: OK");
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

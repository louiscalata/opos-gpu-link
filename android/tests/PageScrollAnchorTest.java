package os.opos.launcher;

public final class PageScrollAnchorTest {
    public static void main(String[] args) {
        int[] bottoms = {200, 500, 900};
        equal(0, PageScrollAnchor.pickAnchorIndex(0, bottoms));
        equal(0, PageScrollAnchor.pickAnchorIndex(199, bottoms));
        equal(1, PageScrollAnchor.pickAnchorIndex(200, bottoms));
        equal(2, PageScrollAnchor.pickAnchorIndex(500, bottoms));
        equal(2, PageScrollAnchor.pickAnchorIndex(800, bottoms));
        equal(2, PageScrollAnchor.pickAnchorIndex(2000, bottoms));
        equal(0, PageScrollAnchor.pickAnchorIndex(0, new int[0]));

        // Growing a card below the viewport top does not move the page.
        equal(100, PageScrollAnchor.adjust(100, 400, 400, 800));
        // A card above the anchor growing by 80 px keeps the same line in view.
        equal(180, PageScrollAnchor.adjust(100, 400, 480, 800));
        // Shrinking a card above pulls the page up, but not past the top.
        equal(0, PageScrollAnchor.adjust(20, 400, 300, 800));
        // Never past the end.
        equal(500, PageScrollAnchor.adjust(400, 100, 300, 500));
        equal(0, PageScrollAnchor.adjust(0, 0, 0, 0));
        System.out.println("PageScrollAnchorTest: OK");
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

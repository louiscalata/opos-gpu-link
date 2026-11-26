package os.opos.launcher;

/**
 * Keeps the page's visible content still while a lane card above the viewport grows
 * during streaming. Host-testable; no Android types.
 */
final class PageScrollAnchor {
    private PageScrollAnchor() {}

    /**
     * Index of the first card whose bottom is below the current scroll position
     * (the first card that still has pixels in or below the viewport top). If
     * every card sits above the viewport, the last card is used.
     */
    static int pickAnchorIndex(int scrollY, int[] bottoms) {
        if (bottoms == null || bottoms.length == 0) return 0;
        for (int i = 0; i < bottoms.length; i++) {
            if (bottoms[i] > scrollY) return i;
        }
        return bottoms.length - 1;
    }

    /**
     * New scrollY after the anchored card's top moves by {@code newTop - oldTop}.
     * A card growing below the anchor leaves the scroll position alone.
     */
    static int adjust(int oldScrollY, int oldAnchorTop, int newAnchorTop, int maxScroll) {
        int next = oldScrollY + (newAnchorTop - oldAnchorTop);
        if (next < 0) return 0;
        if (maxScroll < 0) maxScroll = 0;
        if (next > maxScroll) return maxScroll;
        return next;
    }
}

package os.opos.launcher;

/** Pure scroll arithmetic for answer panes, kept free of Android types so host tests can run it. */
final class ScrollPolicy {
    private ScrollPolicy() {}

    /**
     * Largest scrollY of a ScrollView: content height minus the viewport left after padding,
     * matching ScrollView's own range. Ignoring padding underestimates it by up to one line.
     */
    static int maxScroll(int contentHeight, int viewHeight, int paddingTop, int paddingBottom) {
        int viewport = Math.max(0, viewHeight - Math.max(0, paddingTop) - Math.max(0, paddingBottom));
        return Math.max(0, contentHeight - viewport);
    }

    /**
     * Where to scroll. A request at or past the end (tail follow) lands exactly on the end so the
     * newest line is never clipped; anything else snaps up to a whole line top.
     */
    static int targetScroll(int wanted, int max, int[] lineTops) {
        if (max <= 0) return 0;
        if (wanted >= max) return max;
        return LineSnap.snapTop(Math.max(0, wanted), lineTops);
    }

    /**
     * Whether a render should move the scroll position. A pane that merely stays paused must not be
     * re-aligned on every poll, because that interrupts a fling and snaps the pane backwards; it is
     * aligned once when it enters the paused state, and never while a finger is down.
     */
    static boolean shouldAlign(boolean textChanged, boolean reachedDone,
                               boolean reachedPaused, boolean touching) {
        return textChanged || reachedDone || (reachedPaused && !touching);
    }
}

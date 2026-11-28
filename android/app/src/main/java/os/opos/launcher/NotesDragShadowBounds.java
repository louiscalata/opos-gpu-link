package os.opos.launcher;

/** Keeps a long answer from allocating a full-card bitmap when dragged to Notes. */
final class NotesDragShadowBounds {
    static final int MAX_WIDTH_DP = 480;
    static final int MAX_HEIGHT_DP = 160;

    private NotesDragShadowBounds() {}

    static int pixels(int measured, int limit) {
        return Math.max(1, Math.min(measured, Math.max(1, limit)));
    }
}

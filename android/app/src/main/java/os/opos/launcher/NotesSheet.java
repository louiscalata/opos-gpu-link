package os.opos.launcher;

/**
 * Host-testable rules for the Notes folder tab and pull-up sheet.
 * The tab sits directly above the pinned Summary bar; both appear on the
 * inner screen and the cover.
 */
final class NotesSheet {
    enum State { COLLAPSED, HALF, FULL }

    static final int TAB_DP = 36;
    /** The tab's touch height: the 36 dp tab plus a clear strip above it, so it is a 48 dp target. */
    static final int TAB_TOUCH_DP = 48;
    static final int TAB_SLOP_DP = TAB_TOUCH_DP - TAB_DP;
    /** Minimum height reserved for the pinned Summary bar under the Notes tab. */
    static final int SUMMARY_MIN_DP = 56;
    /** Cap so a long report cannot grow the cover dock up over the Ask box. */
    static final int SUMMARY_MAX_COVER_DP = 72;
    /** Inner cap keeps the dock compact without hiding a short report. */
    static final int SUMMARY_MAX_INNER_DP = 140;
    /** In a short wide window, only the Summary heading peeks above the bottom edge. */
    static final int SUMMARY_WIDE_DP = 40;
    /** Fallback bottom padding (tab + summary) when the dock has not been measured. */
    static final int CONTENT_BOTTOM_PAD_DP = TAB_TOUCH_DP + SUMMARY_MIN_DP;
    static final int FLING_PX_S = 600;
    static final int CONFIRM_MS = 1400;
    static final String CONFIRMATION = "Saved to Notes";

    private NotesSheet() {}

    static boolean available(boolean coverMode) {
        return true;
    }

    /** Results scroll padding so cards sit above the Notes tab and the Summary bar. */
    static int contentBottomPad(int notesHeightPx, int summaryHeightPx) {
        return Math.max(0, notesHeightPx) + Math.max(0, summaryHeightPx);
    }

    /**
     * Extra results padding when the collapsed dock is already reserved as
     * padding on the screen itself (so the Ask box stays clear of the tab).
     */
    static int contentBottomPad(int notesHeightPx, int summaryHeightPx, int reservedPx) {
        return Math.max(0, contentBottomPad(notesHeightPx, summaryHeightPx)
                - Math.max(0, reservedPx));
    }

    static int summaryMaxDp(boolean coverMode) {
        return coverMode ? SUMMARY_MAX_COVER_DP : SUMMARY_MAX_INNER_DP;
    }

    static int summaryMaxDp(boolean coverMode, boolean wide) {
        return wide ? SUMMARY_WIDE_DP : summaryMaxDp(coverMode);
    }

    static int summaryMinDp(boolean wide) {
        return wide ? SUMMARY_WIDE_DP : SUMMARY_MIN_DP;
    }

    static int summaryHeight(int measuredPx, int minPx, int maxPx) {
        if (measuredPx <= 0) return minPx;
        return Math.max(minPx, Math.min(maxPx, measuredPx));
    }

    /** Non-empty note blocks, split on blank lines. */
    static int noteCount(CharSequence text) {
        if (text == null) return 0;
        String value = text.toString().trim();
        if (value.isEmpty()) return 0;
        int count = 0;
        for (String block : value.split("\\n\\s*\\n")) {
            if (!block.trim().isEmpty()) count++;
        }
        return count;
    }

    static String tabLabel(int count) {
        return count <= 0 ? "NOTES" : "NOTES · " + count;
    }

    static State onTabTap(State current) {
        return current == State.COLLAPSED ? State.HALF : State.COLLAPSED;
    }

    static State snap(float height, float collapsed, float half, float full, float velocityY) {
        if (velocityY <= -FLING_PX_S) {
            if (height >= (half + full) / 2f) return State.FULL;
            return height < collapsed + 1 ? State.HALF : State.FULL;
        }
        if (velocityY >= FLING_PX_S) {
            if (height <= (collapsed + half) / 2f) return State.COLLAPSED;
            return height > full - 1 ? State.HALF : State.COLLAPSED;
        }
        float dCollapsed = Math.abs(height - collapsed);
        float dHalf = Math.abs(height - half);
        float dFull = Math.abs(height - full);
        if (dCollapsed <= dHalf && dCollapsed <= dFull) return State.COLLAPSED;
        if (dHalf <= dFull) return State.HALF;
        return State.FULL;
    }

    static int height(State state, int collapsed, int half, int full) {
        if (state == State.HALF) return half;
        if (state == State.FULL) return full;
        return collapsed;
    }

    static int halfHeight(int available, int collapsed) {
        return Math.max(collapsed, available / 2);
    }

    static int fullHeight(int available, int collapsed) {
        return Math.max(collapsed, available);
    }

    /** Extra bottom inset so the tab stays above the system gesture area. */
    static int dockInset(int systemBarBottom, int gestureBottom, int imeBottom) {
        int bottom = Math.max(systemBarBottom, imeBottom);
        return Math.max(bottom, Math.max(0, gestureBottom));
    }
}

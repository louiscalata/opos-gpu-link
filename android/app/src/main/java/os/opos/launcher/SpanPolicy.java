package os.opos.launcher;

/** Span mode selection. */
final class SpanPolicy {
    enum Mode {
        NONE,
        SIDE_BY_SIDE
    }

    static final int MIN_PANE_DP = 320;

    private SpanPolicy() {
    }

    static Mode resolve(SpanGeometry g, int densityDpi) {
        if (densityDpi <= 0 || !verticalHinge(g)) {
            return Mode.NONE;
        }

        // Compare in pixels so rounding never lets a pane that is under the minimum through.
        long minPanePx = (long) MIN_PANE_DP * densityDpi;
        long leftPx = (long) g.hingeLeft * 160;
        long rightPx = (long) (g.windowW - g.hingeRight) * 160;
        if (leftPx >= minPanePx && rightPx >= minPanePx) {
            return Mode.SIDE_BY_SIDE;
        }
        return Mode.NONE;
    }

    /** A hinge inside a real window that runs the full height with room on both sides. */
    static boolean verticalHinge(SpanGeometry g) {
        return g != null && g.windowW > 0 && g.windowH > 0 && g.hasHinge()
                && g.hingeTop <= 0 && g.hingeBottom >= g.windowH
                && g.hingeLeft > 0 && g.hingeRight < g.windowW;
    }

    static int pxToDp(int px, int densityDpi) {
        if (densityDpi <= 0) {
            return 0;
        }
        return (int) (((long) px * 160 + (densityDpi / 2)) / densityDpi);
    }
}

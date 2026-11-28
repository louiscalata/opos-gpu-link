package os.opos.launcher;

/** Window span geometry in window coordinates. */
final class SpanGeometry {
    static final SpanGeometry NONE = new SpanGeometry(0, 0, 0, 0, 0, 0);

    public final int windowW;
    public final int windowH;
    public final int hingeLeft;
    public final int hingeTop;
    public final int hingeRight;
    public final int hingeBottom;

    private SpanGeometry(int windowW, int windowH, int hingeLeft, int hingeTop, int hingeRight, int hingeBottom) {
        this.windowW = windowW;
        this.windowH = windowH;
        this.hingeLeft = hingeLeft;
        this.hingeTop = hingeTop;
        this.hingeRight = hingeRight;
        this.hingeBottom = hingeBottom;
    }

    static SpanGeometry of(int windowW, int windowH, int hl, int ht, int hr, int hb) {
        return new SpanGeometry(windowW, windowH, hl, ht, hr, hb);
    }

    boolean hasHinge() {
        return hingeRight > hingeLeft && hingeBottom > hingeTop;
    }

    @Override
    public boolean equals(Object other) {
        if (this == other) {
            return true;
        }
        if (!(other instanceof SpanGeometry)) {
            return false;
        }
        SpanGeometry that = (SpanGeometry) other;
        return windowW == that.windowW
                && windowH == that.windowH
                && hingeLeft == that.hingeLeft
                && hingeTop == that.hingeTop
                && hingeRight == that.hingeRight
                && hingeBottom == that.hingeBottom;
    }

    @Override
    public int hashCode() {
        int result = windowW;
        result = 31 * result + windowH;
        result = 31 * result + hingeLeft;
        result = 31 * result + hingeTop;
        result = 31 * result + hingeRight;
        result = 31 * result + hingeBottom;
        return result;
    }

    @Override
    public String toString() {
        return "SpanGeometry{"
                + "windowW=" + windowW
                + ", windowH=" + windowH
                + ", hingeLeft=" + hingeLeft
                + ", hingeTop=" + hingeTop
                + ", hingeRight=" + hingeRight
                + ", hingeBottom=" + hingeBottom
                + '}';
    }
}

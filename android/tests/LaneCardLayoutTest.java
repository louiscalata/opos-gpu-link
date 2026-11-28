package os.opos.launcher;

public final class LaneCardLayoutTest {
    public static void main(String[] args) {
        check(LaneCardLayout.wrapsToContent());
        equal(0.5f, LaneCardLayout.STROKE_DP);
        equal(8, LaneCardLayout.CARD_PADDING_DP);
        check(LaneCardLayout.CARD_PADDING_DP < 12);
        equal(6, LaneCardLayout.CARD_GAP_DP);
        equal(17, LaneCardLayout.BODY_SP_FULL);
        equal(17, LaneCardLayout.bodySp(false, false));
        equal(17, LaneCardLayout.bodySp(false, true));
        equal(TypeConfig.body().coverSizeSp, LaneCardLayout.bodySp(true, false));
        equal(14, LaneCardLayout.bodySp(true, false));
        equal(11, LaneCardLayout.LABEL_SP);
        equal(TypeConfig.subheader().sizeSp, LaneCardLayout.LABEL_SP);
        check(LaneCardLayout.LABEL_SP < LaneCardLayout.BODY_SP_FULL);
        equal(21, LaneCardLayout.headingSp(false, true));
        equal(21, LaneCardLayout.headingSp(false, false));
        equal(21, LaneCardLayout.headingSp(true, false));
        equal(LaneCardLayout.headingSp(false, true), LaneCardLayout.headingSp(true, false));
        equal(TypeConfig.header().sizeSp, LaneCardLayout.headingSp(false));
        equal(TypeConfig.header().coverSizeSp, LaneCardLayout.headingSp(true));
        equal(0, LaneCardLayout.gapDp(0));
        equal(6, LaneCardLayout.gapDp(3));
        check(LaneCardLayout.GROW_MS > 0 && LaneCardLayout.GROW_MS <= 200);
        equal(140, LaneCardLayout.GROW_MS);
        equal("#5C5C5C", UiPalette.STROKE);
        int stroke = Integer.parseInt(UiPalette.STROKE.substring(1), 16);
        // Darker than the #fff text and than the #BFBFBF label; still a visible boundary.
        check(stroke < 0xFFFFFF);
        check(stroke < 0x8A8A8A);
        check(contrastOnBlack(stroke) >= 3.0);
        check(contrastOnBlack(stroke) < contrastOnBlack(0xBFBFBF) / 2);
        System.out.println("LaneCardLayoutTest: OK");
    }

    /** WCAG contrast of a gray against #000. */
    private static double contrastOnBlack(int rgb) {
        double c = ((rgb >> 16) & 0xFF) / 255.0;
        double lin = c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        return (lin + 0.05) / 0.05;
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }

    private static void equal(float expected, float actual) {
        if (Math.abs(expected - actual) > 0.0001f) throw new AssertionError(expected + " != " + actual);
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

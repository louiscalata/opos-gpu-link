package os.opos.launcher;

public final class HeatMeterTest {
    public static void main(String[] args) {
        check(HeatMeter.cool(0) && HeatMeter.cool(1), "0 and 1 are cool (ink)");
        check(!HeatMeter.cool(2) && !HeatMeter.hot(2), "warm stays neutral");
        for (int s = 3; s <= 6; s++) {
            check(!HeatMeter.cool(s), "hot is not cool: " + s);
            check(HeatMeter.hot(s), "hot is red: " + s);
        }
        for (int s : new int[] {-1, 0, 1, 2, 7}) {
            check(!HeatMeter.hot(s), "only 3 through 6 are hot: " + s);
        }
        check(!HeatMeter.cool(-1) && !HeatMeter.known(-1) && !HeatMeter.known(7), "unknown hidden");
        equal("● Phone cool", HeatMeter.label(0, false));
        equal("● Phone cool", HeatMeter.label(1, false));
        equal("● Phone warm", HeatMeter.label(2, false));
        equal("● Phone hot", HeatMeter.label(3, false));
        equal("● Phone very hot", HeatMeter.label(4, false));
        equal("● Phone too hot", HeatMeter.label(5, false));
        equal("● Phone too hot", HeatMeter.label(6, false));
        equal("● too hot", HeatMeter.label(5, true));
        equal("● warm", HeatMeter.label(2, true));
        equal("● cool", HeatMeter.label(0, true));
        check(HeatMeter.TEXT_SP > 13 && HeatMeter.TEXT_SP_COMPACT >= 13, "meter reads bigger than status");
        equal("", HeatMeter.label(-1, false));
        equal("", HeatMeter.label(9, true));
        equal("Phone heat 3, hot", HeatMeter.description(3));
        equal("", HeatMeter.description(-2));
        System.out.println("HeatMeterTest OK");
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError("expected <" + expected + "> but was <" + actual + ">");
        }
    }

    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
}

package os.opos.launcher;

public final class HeatMeterTest {
    public static void main(String[] args) {
        check(HeatMeter.cool(0) && HeatMeter.cool(1), "0 and 1 are cool (green)");
        for (int s = 2; s <= 6; s++) check(!HeatMeter.cool(s), "warm or hot is red: " + s);
        check(!HeatMeter.cool(-1) && !HeatMeter.known(-1) && !HeatMeter.known(7), "unknown hidden");
        equal("● Heat 0 · cool", HeatMeter.label(0, false));
        equal("● Heat 1 · cool", HeatMeter.label(1, false));
        equal("● Heat 2 · warm", HeatMeter.label(2, false));
        equal("● Heat 3 · hot", HeatMeter.label(3, false));
        equal("● Heat 4 · very hot", HeatMeter.label(4, false));
        equal("● Heat 6 · too hot", HeatMeter.label(6, false));
        equal("● 2 warm", HeatMeter.label(2, true));
        equal("● 0 cool", HeatMeter.label(0, true));
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

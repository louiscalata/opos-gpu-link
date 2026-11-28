package os.opos.launcher;

public final class RetryControlsTest {
    public static void main(String[] args) {
        check(RetryControls.laneEnabled("phone", false, true, true, false, false));
        check(RetryControls.laneEnabled("m1", false, true, true, false, false));
        check(!RetryControls.laneEnabled("gpu", false, true, true, false, false));
        check(!RetryControls.laneEnabled("gpu", false, false, true, false, false));
        check(RetryControls.laneEnabled("gpu", true, true, true, false, false));
        check(!RetryControls.laneEnabled("phone", false, true, false, false, false));
        check(!RetryControls.laneEnabled("phone", false, true, true, true, false));
        check(!RetryControls.laneEnabled("phone", false, true, true, false, true));
        System.out.println("RetryControlsTest: OK");
    }

    private static void check(boolean condition) {
        if (!condition) throw new AssertionError("retry control state");
    }
}

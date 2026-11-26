package os.opos.launcher;

/** Host checks for the read-only 10-minute screen timeout guidance. */
public final class ScreenTimeoutPreflightTest {
    public static void main(String[] args) {
        unknown(ScreenTimeoutPreflight.assess(-1));
        unknown(ScreenTimeoutPreflight.assess(0));
        known(ScreenTimeoutPreflight.assess(5 * 60 * 1000), true, "5 min");
        known(ScreenTimeoutPreflight.assess(10 * 60 * 1000), false, "10 min");
        known(ScreenTimeoutPreflight.assess(12 * 60 * 1000 + 30 * 1000),
                false, "12 min 30 sec");
        known(ScreenTimeoutPreflight.assess(10 * 60 * 1000 - 1),
                true, "9 min 59 sec");
        System.out.println("ScreenTimeoutPreflightTest: OK");
    }

    private static void unknown(ScreenTimeoutPreflight.Result result) {
        if (result.known || result.shorterThanTenMinutes || !result.duration.isEmpty()) {
            throw new AssertionError("Expected unknown timeout");
        }
    }

    private static void known(ScreenTimeoutPreflight.Result result,
                              boolean shorter, String duration) {
        if (!result.known || result.shorterThanTenMinutes != shorter
                || !duration.equals(result.duration)) {
            throw new AssertionError("Unexpected timeout result: " + result.duration);
        }
    }
}

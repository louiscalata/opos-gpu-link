package os.opos.launcher;

/** Host checks for a same-label PC replacement during Forget confirmation. */
public final class PcFingerprintTest {
    public static void main(String[] args) {
        String first = PcFingerprint.normalized("0123456789abcdef");
        String replacement = PcFingerprint.normalized("fedcba9876543210");
        yes(PcFingerprint.same("Stage PC", first, "Stage PC", first));
        no(PcFingerprint.same("Stage PC", first, "Stage PC", replacement));
        no(PcFingerprint.same("Stage PC", replacement, "Stage PC", first));
        no(PcFingerprint.same("Stage PC", first, null, ""));
        no(PcFingerprint.same("Stage PC", first, "Other PC", first));
        equal("", PcFingerprint.normalized("0123456789abcdeG"));
        equal("", PcFingerprint.normalized(null));
        // The current backend omits an ID. The UI retains its existing label check.
        yes(PcFingerprint.same("Stage PC", "", "Stage PC", ""));
        no(PcFingerprint.same("Stage PC", "", "Stage PC", first));
        no(PcFingerprint.same("Stage PC", "", "Other PC", ""));
        System.out.println("PcFingerprintTest: OK");
    }

    private static void yes(boolean value) {
        if (!value) throw new AssertionError("Expected true");
    }

    private static void no(boolean value) {
        if (value) throw new AssertionError("Expected false");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError("Expected " + expected + " but got " + actual);
    }
}

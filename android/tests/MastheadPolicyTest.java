package os.opos.launcher;

public final class MastheadPolicyTest {
    public static void main(String[] args) {
        equal(1f, MastheadPolicy.bigAlpha(0f));
        equal(0f, MastheadPolicy.smallAlpha(0f));
        equal(0f, MastheadPolicy.bigAlpha(1f));
        equal(1f, MastheadPolicy.smallAlpha(1f));
        // Instant hand-off: the name is always fully on or fully off, never ghosted.
        for (int i = 0; i <= 1000; i++) {
            float fraction = i / 1000f;
            if (MastheadPolicy.overlaps(fraction)) {
                throw new AssertionError("both titles visible at " + fraction);
            }
            float big = MastheadPolicy.bigAlpha(fraction);
            float small = MastheadPolicy.smallAlpha(fraction);
            if ((big != 0f && big != 1f) || (small != 0f && small != 1f)) {
                throw new AssertionError("faded title at " + fraction);
            }
            float sum = big + small;
            if (Math.abs(sum - 1f) > 0.0001f) {
                throw new AssertionError("combined opacity " + sum + " at " + fraction);
            }
        }
        equal(0f, MastheadPolicy.bigAlpha(0.5f));
        equal(1f, MastheadPolicy.smallAlpha(0.5f));
        equal(1f, MastheadPolicy.bigAlpha(0.25f));
        equal(0f, MastheadPolicy.smallAlpha(0.25f));
        equal(0f, MastheadPolicy.bigAlpha(0.75f));
        equal(1f, MastheadPolicy.smallAlpha(0.75f));
        equal(1f, MastheadPolicy.bigAlpha(-1f));
        equal(1f, MastheadPolicy.smallAlpha(2f));
        System.out.println("MastheadPolicyTest: OK");
    }

    private static void equal(float expected, float actual) {
        if (Math.abs(expected - actual) > 0.0001f) throw new AssertionError(expected + " != " + actual);
    }
}

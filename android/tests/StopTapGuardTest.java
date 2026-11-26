package os.opos.launcher;

public final class StopTapGuardTest {
    public static void main(String[] args) {
        // Never asked: Stop works.
        check(!StopTapGuard.ignore(10_000L, -1L));
        // Second and third taps of a double or triple tap on Send (live Flip 6, 26 Nov 2026).
        check(StopTapGuard.ignore(10_000L, 10_000L));
        check(StopTapGuard.ignore(10_150L, 10_000L));
        check(StopTapGuard.ignore(10_799L, 10_000L));
        // A deliberate Stop after the grace window works.
        check(!StopTapGuard.ignore(10_800L, 10_000L));
        check(!StopTapGuard.ignore(25_000L, 10_000L));
        // Clock oddity (ask stamped after now): do not swallow the tap.
        check(!StopTapGuard.ignore(9_000L, 10_000L));
        System.out.println("StopTapGuardTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError("check failed");
    }
}

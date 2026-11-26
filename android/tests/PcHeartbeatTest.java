package os.opos.launcher;

/** Host-only regression for live PC followed by a no-PC snapshot. */
public final class PcHeartbeatTest {
    public static void main(String[] args) {
        long[] live = PcHeartbeat.afterSnapshot(true, true, true, 1000, 0, 0);
        equal(1000, live[0]);
        equal(1000, live[1]);
        yes(PcHeartbeat.readyGrace(true, live[1], 1100, 500));

        long[] gone = PcHeartbeat.afterSnapshot(false, false, false, 1100,
                live[0], live[1]);
        equal(0, gone[0]);
        equal(0, gone[1]);
        no(PcHeartbeat.readyGrace(false, live[1], 1100, 500));
        no(PcHeartbeat.liveGrace(false, live[0], 1100, 500));

        long[] transientLoss = PcHeartbeat.afterSnapshot(true, false, false, 1200,
                live[0], live[1]);
        equal(1000, transientLoss[0]);
        equal(1000, transientLoss[1]);
        no(PcHeartbeat.readyGrace(true, live[1], 1600, 500));
        System.out.println("PcHeartbeatTest: OK");
    }

    private static void yes(boolean value) {
        if (!value) throw new AssertionError("Expected true");
    }

    private static void no(boolean value) {
        if (value) throw new AssertionError("Expected false");
    }

    private static void equal(long expected, long actual) {
        if (expected != actual) throw new AssertionError("Expected " + expected + " but got " + actual);
    }
}

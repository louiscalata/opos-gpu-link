package os.opos.launcher;

/** Small state rule shared by the header and Info status. */
final class PcHeartbeat {
    private PcHeartbeat() {}

    static long[] afterSnapshot(boolean hasPc, boolean live, boolean ready,
                                long now, long lastLive, long lastGood) {
        if (!hasPc) return new long[] {0, 0};
        if (!live) return new long[] {lastLive, lastGood};
        return new long[] {now, ready ? now : lastGood};
    }

    static boolean readyGrace(boolean hasPc, long lastGood, long now, long holdMs) {
        return hasPc && lastGood > 0 && now - lastGood < holdMs;
    }

    static boolean liveGrace(boolean hasPc, long lastLive, long now, long holdMs) {
        return hasPc && lastLive > 0 && now - lastLive < holdMs;
    }
}

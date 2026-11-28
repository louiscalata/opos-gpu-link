package os.opos.launcher;

/** Layout and link wording shared by the inner page and the Flip cover. */
final class DeviceLayoutPolicy {
    static final int TWO_COLUMN_MIN_WIDTH_DP = 600;

    enum Side { PHONE, COMPUTER, UNKNOWN }
    enum LinkState { CONNECTED, CABLE_OUT, PAUSED, ERROR, WAITING }

    private DeviceLayoutPolicy() {}

    static int columns(int widthDp, boolean cover, int laneCount) {
        return !cover && widthDp >= TWO_COLUMN_MIN_WIDTH_DP && laneCount > 1 ? 2 : 1;
    }

    /** The service's kind is authoritative for extra lanes; known pane keys are the fallback. */
    static Side side(String pane, String kind) {
        if ("phone".equals(kind)) return Side.PHONE;
        if ("pc".equals(kind)) return Side.COMPUTER;
        if (!PaneKeys.valid(pane)) return Side.UNKNOWN;
        return PaneKeys.pc(pane) ? Side.COMPUTER : Side.PHONE;
    }

    /** The first card from each device stays by its panel; later cards use free columns. */
    static Side column(Side side, int phoneCards, int computerCards) {
        if (side == Side.UNKNOWN) return phoneCards <= computerCards ? Side.PHONE : Side.COMPUTER;
        if (side == Side.PHONE && phoneCards > computerCards) return Side.COMPUTER;
        if (side == Side.COMPUTER && computerCards > phoneCards) return Side.PHONE;
        return side;
    }

    static LinkState linkState(Boolean cable, boolean connected, boolean paused, boolean error) {
        if (Boolean.FALSE.equals(cable)) return LinkState.CABLE_OUT;
        if (error) return LinkState.ERROR;
        if (paused) return LinkState.PAUSED;
        if (Boolean.TRUE.equals(cable) && connected) return LinkState.CONNECTED;
        return LinkState.WAITING;
    }

    static String linkLabel(LinkState state) {
        switch (state) {
            case CONNECTED: return "USB-C\nConnected";
            case CABLE_OUT: return "USB-C\nCable out";
            case PAUSED: return "USB-C\nPaused";
            case ERROR: return "USB-C\nError";
            default: return "USB-C\nWaiting";
        }
    }

    static String description(String computer, LinkState state) {
        String name = computer == null || computer.trim().isEmpty() ? "computer" : computer.trim();
        switch (state) {
            case CONNECTED: return "Phone connected to " + name + " by USB-C";
            case CABLE_OUT: return "Phone and " + name + ": cable out";
            case PAUSED: return "Phone and " + name + ": connection paused";
            case ERROR: return "Phone and " + name + ": connection error";
            default: return "Phone waiting for " + name + " over USB-C";
        }
    }
}

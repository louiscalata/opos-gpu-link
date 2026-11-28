package os.opos.launcher;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;

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

    /** Primary computer answer first in portrait; the phone comparison baseline follows the other phone answers. */
    static List<String> orderedPanes(List<String> panes, Map<String, String> kinds) {
        List<String> ordered = new ArrayList<>(panes);
        ordered.sort(Comparator.comparingInt(pane -> orderRank(pane, kinds.get(pane))));
        return ordered;
    }

    private static int orderRank(String pane, String kind) {
        if ("gpu".equals(pane)) return 0;
        if ("phone".equals(pane)) return 3;
        Side side = side(pane, kind);
        if (side == Side.PHONE) return 1;
        if (side == Side.COMPUTER) return 2;
        return 4;
    }

    /** Known phone cards stay left and known computer cards stay right. */
    static Side column(Side side, int phoneCards, int computerCards) {
        if (side == Side.UNKNOWN) return phoneCards <= computerCards ? Side.PHONE : Side.COMPUTER;
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
        return description("Phone", computer, state);
    }

    static String phoneName(String configured, String model) {
        // Samsung's SM-F741 family is the Galaxy Z Flip6 used for the demo.
        if (model != null && model.trim().regionMatches(true, 0, "SM-F741", 0, 7)) {
            return "Galaxy Z Flip 6";
        }
        if (configured != null && !configured.trim().isEmpty()
                && !"null".equalsIgnoreCase(configured.trim())) return configured.trim();
        if (model != null && !model.trim().isEmpty()
                && !"null".equalsIgnoreCase(model.trim())) return model.trim();
        return "Phone";
    }

    static String description(String phone, String computer, LinkState state) {
        String device = phoneName(phone, null);
        String name = computer == null || computer.trim().isEmpty() ? "computer" : computer.trim();
        switch (state) {
            case CONNECTED: return device + " connected to " + name + " by USB-C";
            case CABLE_OUT: return device + " and " + name + ": cable out";
            case PAUSED: return device + " and " + name + ": connection paused";
            case ERROR: return device + " and " + name + ": connection error";
            default: return device + " waiting for " + name + " over USB-C";
        }
    }
}

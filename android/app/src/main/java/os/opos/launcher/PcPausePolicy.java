package os.opos.launcher;

import java.util.ArrayList;
import java.util.List;

/** Keeps every PC article stable while its link is absent or the backend has paused it. */
final class PcPausePolicy {
    private PcPausePolicy() {}

    static boolean openState(String state) {
        return "queued".equals(state) || "waiting".equals(state)
                || "loading".equals(state) || "answering".equals(state)
                || "paused".equals(state);
    }

    static boolean paused(String pane, String state, Boolean cableConnected) {
        return PaneKeys.pc(pane) && ("paused".equals(state)
                || Boolean.FALSE.equals(cableConnected) && openState(state));
    }

    static String textToDisplay(String pane, String state, boolean currentRequest,
                                String previous, String incoming) {
        if (PaneKeys.pc(pane) && currentRequest && openState(state)
                && (incoming == null || incoming.isEmpty())
                && previous != null && !previous.isEmpty()) return previous;
        return incoming == null ? "" : incoming;
    }

    static List<String> visiblePanes(List<String> shown, List<String> selected,
                                     Boolean cableConnected) {
        return new ArrayList<>(Boolean.FALSE.equals(cableConnected) ? shown : selected);
    }
}

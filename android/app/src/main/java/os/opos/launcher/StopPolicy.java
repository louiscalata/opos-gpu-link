package os.opos.launcher;

import java.util.ArrayList;
import java.util.Collection;
import java.util.List;
import java.util.Map;

/** Decides whether a Stop that hit an error still needs the "could not be stopped" line. */
final class StopPolicy {
    private StopPolicy() {}

    /**
     * A cancel can be refused because the answer finished between the snapshot Stop read and
     * the cancel request. If a fresh snapshot shows none of the targeted answers still open,
     * nothing is left running and the error line would be wrong.
     */
    static boolean stillRunning(Collection<String> targeted, Collection<String> openAfter) {
        if (targeted == null || targeted.isEmpty() || openAfter == null) return true;
        for (String id : targeted) {
            if (openAfter.contains(id)) return true;
        }
        return false;
    }

    /** A legacy host reports this exact refusal because it accepts "id", not "ids". */
    static boolean legacyBulkUnsupported(int status, String message) {
        return status == 400 && "That answer was not found.".equals(message);
    }

    /** An open pane without an ID cannot be included in a cancel request. */
    static boolean hasOpenWithoutId(Collection<String> idsByOpenPane) {
        if (idsByOpenPane == null) return false;
        for (String id : idsByOpenPane) {
            if (id == null || id.isEmpty()) return true;
        }
        return false;
    }

    /** Keep the Stop notice while an unnamed answer can still block a new Send. */
    static boolean noIdStillOpen(boolean blocking, Collection<String> idsByOpenPane) {
        return blocking && hasOpenWithoutId(idsByOpenPane);
    }

    /** A fresh snapshot, or a usable response after cancel, must show no open answers. */
    static boolean quitConfirmedStopped(boolean beforeFresh, boolean openBefore,
                                        boolean afterUsable, boolean openAfter) {
        if (afterUsable) return !openAfter;
        return beforeFresh && !openBefore;
    }

    /** Stop queued phone lanes before ending the lead answer on a one-ID host. */
    static List<String> waitingFirst(List<String> ids, Map<String, String> states) {
        List<String> result = new ArrayList<>();
        if (ids == null || ids.isEmpty()) return result;
        for (String id : ids) {
            if (waiting(states == null ? null : states.get(id))) result.add(id);
        }
        for (String id : ids) {
            if (!waiting(states == null ? null : states.get(id))) result.add(id);
        }
        return result;
    }

    private static boolean waiting(String state) {
        return "queued".equals(state) || "waiting".equals(state);
    }
}

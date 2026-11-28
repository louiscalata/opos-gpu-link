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

    /** Stop queued phone lanes before ending the lead answer on a one-ID host. */
    static List<String> waitingFirst(List<String> ids, Map<String, String> states) {
        List<String> result = new ArrayList<>();
        for (String id : ids) {
            if (waiting(states.get(id))) result.add(id);
        }
        for (String id : ids) {
            if (!waiting(states.get(id))) result.add(id);
        }
        return result;
    }

    private static boolean waiting(String state) {
        return "queued".equals(state) || "waiting".equals(state);
    }
}

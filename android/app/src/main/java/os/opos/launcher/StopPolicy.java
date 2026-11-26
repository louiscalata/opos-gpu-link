package os.opos.launcher;

import java.util.Collection;

/** Decides whether a Stop that hit an error still needs the "could not be stopped" line. */
final class StopPolicy {
    private StopPolicy() {}

    /**
     * A cancel can be refused because the answer finished between the snapshot Stop read and
     * the cancel request. If a fresh snapshot shows none of the targeted answers still open,
     * nothing is left running and the error line would be wrong.
     */
    static boolean stillRunning(Collection<String> targeted, Collection<String> openAfter) {
        if (targeted == null || openAfter == null) return true;
        for (String id : targeted) {
            if (openAfter.contains(id)) return true;
        }
        return false;
    }
}

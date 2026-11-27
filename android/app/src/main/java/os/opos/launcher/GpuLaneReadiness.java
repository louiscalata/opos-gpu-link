package os.opos.launcher;

/** Host-testable rule for when the computer lane counts as ready for stall and Retry decisions. */
final class GpuLaneReadiness {
    private GpuLaneReadiness() {}

    /**
     * @param mainLive the computer's main worker sent a status recently
     * @param state    its last status state, or null from an older companion
     */
    static boolean ready(boolean mainLive, String state) {
        if (!mainLive) return false;
        return state == null || "ready".equals(state) || "busy".equals(state);
    }
}

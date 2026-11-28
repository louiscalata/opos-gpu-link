package os.opos.launcher;

/** Keeps on-phone Retry available while an independent computer lane has lost its cable. */
final class RetryControls {
    private RetryControls() {}

    static boolean laneEnabled(String pane, Boolean cableConnected, boolean laneReady,
                               boolean reachable, boolean acting, boolean quitting) {
        return reachable && !acting && !quitting && laneReady
                && (!PaneKeys.pc(pane) || !Boolean.FALSE.equals(cableConnected));
    }
}

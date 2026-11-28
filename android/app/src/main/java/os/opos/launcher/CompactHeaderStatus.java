package os.opos.launcher;

import java.util.List;
import java.util.Map;

/** Keeps the selected phone and PC lane states in the compact sticky region. */
final class CompactHeaderStatus {
    private CompactHeaderStatus() {}

    static String selectedState(List<String> orderedPanes, Map<String, String> states,
                                boolean pc, String notAsked, String checking) {
        for (String pane : orderedPanes) {
            if (PaneKeys.pc(pane) != pc) continue;
            String state = states.get(pane);
            return state == null || state.isEmpty() ? checking : state;
        }
        return notAsked;
    }

    static String line(String phoneLabel, String phoneState, String pcLabel,
                       String pcState, String fullPausedState) {
        String compactPcState = pcState.equals(fullPausedState) ? "Paused"
                : WorkingIndicator.display(pcState);
        return phoneLabel + ": " + WorkingIndicator.display(phoneState)
                + " · " + pcLabel + ": " + compactPcState;
    }
}

package os.opos.launcher;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** A per-lane choice stored locally; the lead lanes stay on until explicitly changed. */
final class LaneSelection {
    interface Store {
        boolean contains(String key);
        boolean get(String key, boolean fallback);
        void put(String key, boolean value);
    }

    private static final String PREFIX = "lane_on_";
    private final Store store;

    LaneSelection(Store store) {
        this.store = store;
    }

    private static String key(String pane) {
        if (!PaneKeys.valid(pane)) throw new IllegalArgumentException("Unknown pane");
        return PREFIX + pane;
    }

    private boolean hasSavedSelection() {
        // Include lanes missing from the current snapshot. A saved choice for a
        // disappeared model must still keep a newly ready model off.
        for (String pane : PaneKeys.knownPanes()) {
            if (store.contains(key(pane))) return true;
        }
        return false;
    }

    List<String> selected(List<String> available, Map<String, Boolean> ready) {
        List<String> result = new ArrayList<>();
        boolean firstChoicePending = !hasSavedSelection();
        for (String pane : available) {
            if (!PaneKeys.valid(pane) || result.contains(pane)) continue;
            String key = key(pane);
            boolean enabled = store.contains(key)
                    ? store.get(key, false)
                    : "phone".equals(pane) || "gpu".equals(pane)
                    || (firstChoicePending && Boolean.TRUE.equals(ready.get(pane)));
            if (enabled) result.add(pane);
        }
        return result;
    }

    boolean isOn(List<String> available, Map<String, Boolean> ready, String pane) {
        return selected(available, ready).contains(pane);
    }

    /** Returns false if the requested change would turn off the last selected lane. */
    boolean set(List<String> available, Map<String, Boolean> ready,
                String pane, boolean enabled) {
        if (!available.contains(pane) || !PaneKeys.valid(pane)) return false;
        List<String> current = selected(available, ready);
        if (!enabled && current.contains(pane) && current.size() == 1) return false;
        if (!hasSavedSelection()) {
            // The first toggle freezes all choices currently shown, so saving
            // one change does not unexpectedly turn the other defaults off.
            for (String shown : available) {
                if (PaneKeys.valid(shown)) store.put(key(shown), current.contains(shown));
            }
        }
        store.put(key(pane), enabled);
        return true;
    }

    List<String> eligible(List<String> available, Map<String, Boolean> ready) {
        List<String> on = selected(available, ready);
        List<String> result = new ArrayList<>();
        for (String pane : available) {
            if (on.contains(pane) && Boolean.TRUE.equals(ready.get(pane))) result.add(pane);
        }
        return result;
    }
}

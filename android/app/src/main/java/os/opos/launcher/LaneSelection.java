package os.opos.launcher;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** A per-lane opt-in stored locally, with ready lanes on by default. */
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

    List<String> selected(List<String> available, Map<String, Boolean> ready) {
        List<String> result = new ArrayList<>();
        for (String pane : available) {
            if (!PaneKeys.valid(pane) || result.contains(pane)) continue;
            String key = key(pane);
            boolean enabled = store.contains(key)
                    ? store.get(key, false) : "phone".equals(pane) || "gpu".equals(pane)
                    || Boolean.TRUE.equals(ready.get(pane));
            if (enabled) result.add(pane);
        }
        // A chosen model can disappear from the next snapshot. Respect saved OFF choices;
        // never silently run another model in its place.
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

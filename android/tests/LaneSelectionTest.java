package os.opos.launcher;

import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class LaneSelectionTest {
    public static void main(String[] args) {
        Map<String, Boolean> values = new HashMap<>();
        LaneSelection.Store memory = new LaneSelection.Store() {
            public boolean contains(String key) { return values.containsKey(key); }
            public boolean get(String key, boolean fallback) { return values.getOrDefault(key, fallback); }
            public void put(String key, boolean value) { values.put(key, value); }
        };
        LaneSelection selection = new LaneSelection(memory);
        List<String> panes = Arrays.asList("phone", "gpu", "m1", "g1");
        Map<String, Boolean> ready = new HashMap<>();
        ready.put("phone", true);
        ready.put("gpu", true);
        ready.put("m1", false);
        ready.put("g1", false);
        equal(Arrays.asList("phone", "gpu"), selection.selected(panes, ready));
        equal(Arrays.asList("phone", "gpu"), selection.eligible(panes, ready));
        check(selection.set(panes, ready, "gpu", false));
        equal(Arrays.asList("phone"), new LaneSelection(memory).selected(panes, ready));
        check(!selection.set(panes, ready, "phone", false));
        check(selection.set(panes, ready, "g1", true));
        equal(Arrays.asList("phone", "g1"), selection.selected(panes, ready));
        ready.put("g1", true);
        equal(Arrays.asList("phone", "g1"), selection.eligible(panes, ready));
        ready.put("m1", true);
        equal(Arrays.asList("phone", "m1", "g1"), selection.selected(panes, ready));
        check(!selection.set(panes, ready, "m5", true));
        Map<String, Boolean> noneReady = new HashMap<>();
        equal(Arrays.asList("phone", "gpu"), new LaneSelection(new LaneSelection.Store() {
            public boolean contains(String key) { return false; }
            public boolean get(String key, boolean fallback) { return fallback; }
            public void put(String key, boolean value) {}
        }).selected(panes, noneReady));
        List<String> nine = PaneKeys.orderedPanes(Arrays.asList(
                "m1", "m2", "m3", "m4", "g1", "g2", "g3"));
        Map<String, Boolean> nineReady = new HashMap<>();
        for (String pane : nine) nineReady.put(pane, true);
        nineReady.put("g2", false);
        LaneSelection allOn = new LaneSelection(new LaneSelection.Store() {
            public boolean contains(String key) { return false; }
            public boolean get(String key, boolean fallback) { return fallback; }
            public void put(String key, boolean value) {}
        });
        equal(Arrays.asList("phone", "gpu", "m1", "m2", "m3", "m4", "g1", "g3"),
                PaneKeys.readyPanes(nine, readyForSelected(nine, allOn, nineReady)));
        System.out.println("LaneSelectionTest: OK");
    }

    private static Map<String, Boolean> readyForSelected(List<String> panes,
            LaneSelection selection, Map<String, Boolean> ready) {
        Map<String, Boolean> eligible = new HashMap<>();
        List<String> selected = selection.selected(panes, ready);
        for (String pane : panes) {
            eligible.put(pane, selected.contains(pane) && Boolean.TRUE.equals(ready.get(pane)));
        }
        return eligible;
    }

    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void equal(List<String> expected, List<String> actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

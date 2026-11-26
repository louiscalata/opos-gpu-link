package os.opos.launcher;

import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class PaneKeysTest {
    public static void main(String[] args) {
        for (String pane : new String[]{"phone", "gpu", "m1", "m2", "m3", "m4"}) {
            check(PaneKeys.valid(pane));
            equal("latest_" + pane + "_id", PaneKeys.pref(pane, "latest_id"));
            equal("latest_" + pane + "_requested", PaneKeys.pref(pane, "requested"));
            equal("previous_" + pane + "_id", PaneKeys.pref(pane, "previous_id"));
        }
        check(!PaneKeys.valid("m5"));
        check(!PaneKeys.extra("gpu"));
        check(PaneKeys.extra("m4"));
        List<String> ordered = PaneKeys.orderedPanes(
                Arrays.asList("m2", "m1", "m2", "m4", "m5", "m3"));
        equal(Arrays.asList("phone", "gpu", "m2", "m1", "m4", "m3"), ordered);
        Map<String, Boolean> ready = new HashMap<>();
        ready.put("phone", true);
        ready.put("gpu", true);
        ready.put("m2", true);
        ready.put("m1", false);
        ready.put("m4", true);
        equal(Arrays.asList("phone", "gpu", "m2", "m4"),
                PaneKeys.readyPanes(ordered, ready));
        Map<String, String> open = new HashMap<>();
        open.put("phone", "a");
        open.put("gpu", "b");
        open.put("m2", "c");
        open.put("m1", "c");
        open.put("m4", "");
        equal(Arrays.asList("a", "b", "c"), PaneKeys.uniqueOpenIds(ordered, open));
        try {
            PaneKeys.pref("m5", "latest_id");
            throw new AssertionError("Unknown pane accepted");
        } catch (IllegalArgumentException expected) {}
        System.out.println("PaneKeysTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }

    private static void equal(List<String> expected, List<String> actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

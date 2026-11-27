package os.opos.launcher;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Stable pane names and preference keys; legacy phone/GPU keys remain intact. */
final class PaneKeys {
    private PaneKeys() {}

    static boolean valid(String pane) {
        return "phone".equals(pane) || "gpu".equals(pane)
                || "m1".equals(pane) || "m2".equals(pane)
                || "m3".equals(pane) || "m4".equals(pane)
                || "g1".equals(pane) || "g2".equals(pane)
                || "g3".equals(pane);
    }

    static boolean extra(String pane) {
        return "m1".equals(pane) || "m2".equals(pane)
                || "m3".equals(pane) || "m4".equals(pane)
                || "g1".equals(pane) || "g2".equals(pane)
                || "g3".equals(pane);
    }

    static boolean pc(String pane) {
        return "gpu".equals(pane) || "g1".equals(pane)
                || "g2".equals(pane) || "g3".equals(pane);
    }

    static boolean modelKindMatches(String pane, String kind) {
        return extra(pane) && (kind == null || kind.isEmpty()
                || (pc(pane) ? "pc".equals(kind) : "phone".equals(kind)));
    }

    static String kicker(String pane) {
        return kicker(pane, ComputerWords.current());
    }

    static String kicker(String pane, String computer) {
        // Where the model runs, the same word on every card: "MacBook GPU" or "Phone".
        return pc(pane) ? ComputerWords.apply("PC GPU", computer) : "PHONE";
    }

    static String defaultWhere(String pane) {
        return pc(pane) ? ComputerWords.apply("on the PC's GPU") : "on this phone";
    }

    /** The phone service's own default ("on the PC's GPU") is worded for the paired computer. */
    static String shownWhere(String pane, String where) {
        String value = where == null ? "" : where.trim();
        if (value.isEmpty() || "unknown".equalsIgnoreCase(value) || "on the PC's GPU".equals(value)) {
            return defaultWhere(pane);
        }
        return value;
    }

    static String pref(String pane, String field) {
        if (!valid(pane)) throw new IllegalArgumentException("Unknown pane");
        if ("latest_id".equals(field)) return "latest_" + pane + "_id";
        if ("requested".equals(field)) return "latest_" + pane + "_requested";
        if ("previous_id".equals(field)) return "previous_" + pane + "_id";
        throw new IllegalArgumentException("Unknown field");
    }

    static List<String> orderedPanes(List<String> modelPanes) {
        List<String> result = new ArrayList<>();
        result.add("phone");
        result.add("gpu");
        for (String pane : modelPanes) {
            if (extra(pane) && !result.contains(pane)) result.add(pane);
        }
        return result;
    }

    static List<String> readyPanes(List<String> ordered, Map<String, Boolean> eligible) {
        List<String> result = new ArrayList<>();
        for (String pane : ordered) {
            if (valid(pane) && Boolean.TRUE.equals(eligible.get(pane))) result.add(pane);
        }
        return result;
    }

    static List<String> uniqueOpenIds(List<String> ordered, Map<String, String> ids) {
        List<String> result = new ArrayList<>();
        Set<String> seen = new HashSet<>();
        for (String pane : ordered) {
            String id = ids.get(pane);
            if (valid(pane) && id != null && !id.isEmpty() && seen.add(id)) result.add(id);
        }
        return result;
    }
}

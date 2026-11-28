package os.opos.launcher;

import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/** Stable pane names and preference keys; legacy phone/GPU keys remain intact. */
final class PaneKeys {
    private static final List<String> KNOWN_PANES = List.of(
            "phone", "gpu", "m1", "m2", "m3", "m4", "g1", "g2", "g3");

    private PaneKeys() {}

    static boolean valid(String pane) {
        return KNOWN_PANES.contains(pane);
    }

    static List<String> knownPanes() { return KNOWN_PANES; }

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

    /** Old saved answers may lack the computer's name; keep their place neutral. */
    static String archivedWhere(String where) {
        String value = where == null ? "" : where.trim();
        if ("on the PC's GPU".equals(value)) return "on the computer's GPU";
        if ("over USB".equals(value)) return "over USB-C";
        return value;
    }

    /** A saved connection description is not the computer's name. */
    static String archivedComputer(String where) {
        String value = archivedWhere(where);
        if (value.isEmpty() || "unknown".equalsIgnoreCase(value)
                || "on the computer's GPU".equals(value) || "over USB-C".equals(value)) {
            return ComputerWords.COMPUTER;
        }
        return ComputerWords.noun(value);
    }

    static String fallbackLabel(String pane) {
        if ("m3".equals(pane)) return "Phone model 3 (baseline)";
        if ("m1".equals(pane)) return "Phone model 1";
        if ("m2".equals(pane)) return "Phone model 2";
        if ("m4".equals(pane)) return "Phone model 4";
        if ("g1".equals(pane)) return "Computer model 1";
        if ("g2".equals(pane)) return "Computer model 2";
        if ("g3".equals(pane)) return "Computer model 3";
        return pc(pane) ? "Computer model" : valid(pane) ? "Phone model" : "Model";
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

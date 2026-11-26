package os.opos.launcher;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/**
 * A bundled typography set the reader can pick in Settings. The default is
 * whatever {@link TypeConfig} currently names as its three picks; those
 * constants are not changed here.
 */
final class TypeChoice {
    static final String DEFAULT = TypeConfig.HEADER + "+" + TypeConfig.SUBHEADER + "+" + TypeConfig.BODY;
    static final String FABLE = "H5+S6+B7";
    static final List<String> OPTIONS = Collections.unmodifiableList(Arrays.asList(
            "H5+S5+B5", "H6+S6+B6", "H7+S7+B7", "H8+S8+B8", FABLE));

    final String id;
    final String headerId;
    final String subheaderId;
    final String bodyId;

    private TypeChoice(String id, String headerId, String subheaderId, String bodyId) {
        this.id = id;
        this.headerId = headerId;
        this.subheaderId = subheaderId;
        this.bodyId = bodyId;
    }

    static TypeChoice defaults() {
        return parse(DEFAULT);
    }

    static TypeChoice parse(String id) {
        if (id == null || !OPTIONS.contains(id)) return parse(DEFAULT);
        String[] parts = id.split("\\+");
        return new TypeChoice(id, parts[0], parts[1], parts[2]);
    }

    TypeConfig.Role header() { return TypeConfig.header(headerId); }
    TypeConfig.Role subheader() { return TypeConfig.subheader(subheaderId); }
    TypeConfig.Role body() { return TypeConfig.body(bodyId); }

    /** Short caption under the set id; not a colour cue. */
    static String caption(String id) {
        switch (id == null ? "" : id) {
            case "H5+S5+B5": return "Optical broadsheet (default)";
            case "H6+S6+B6": return "Newsreader editorial";
            case "H7+S7+B7": return "Perfect-fourth contrast";
            case "H8+S8+B8": return "Quiet text-on-text";
            case "H5+S6+B7": return "Fable";
            default: return "";
        }
    }

    boolean isDefault() {
        return DEFAULT.equals(id);
    }
}

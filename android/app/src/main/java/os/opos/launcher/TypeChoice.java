package os.opos.launcher;

import java.util.Collections;
import java.util.List;

/**
 * The fixed newspaper type set. Older saved choices now read as H5 + S5 + B5.
 */
final class TypeChoice {
    static final String DEFAULT = TypeConfig.HEADER + "+" + TypeConfig.SUBHEADER + "+" + TypeConfig.BODY;
    static final List<String> OPTIONS = Collections.singletonList(DEFAULT);

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
        return new TypeChoice(DEFAULT, TypeConfig.HEADER, TypeConfig.SUBHEADER,
                TypeConfig.BODY);
    }

    TypeConfig.Role header() { return TypeConfig.header(headerId); }
    TypeConfig.Role subheader() { return TypeConfig.subheader(subheaderId); }
    TypeConfig.Role body() { return TypeConfig.body(bodyId); }

    /** Short caption under the set id; not a colour cue. */
    static String caption(String id) {
        return DEFAULT.equals(id) ? "Newspaper type" : "";
    }

    boolean isDefault() {
        return DEFAULT.equals(id);
    }
}

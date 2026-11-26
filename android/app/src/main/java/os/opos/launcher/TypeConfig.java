package os.opos.launcher;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Jaryo-style typography picks for lane cards. The maintainer changes the three IDs
 * below; every card then uses that header, subheader, and body set.
 *
 * Round 1 (H1–H4, S1–S4, B1–B4) is kept for rollback. Round 2 (H5–H8,
 * S5–S8, B5–B8) is a new typographic system: optical sizes, a modular
 * scale, tracking tuned per size, and tabular figures for status and
 * tok/s. Defaults are the recommended pairing H5 + S5 + B5,
 * with panel micro-adjustments: H5 tracking -0.01em, S5 +0.02em,
 * B5 leading 1.35 and tracking 0. Leading is applied as an absolute
 * baseline distance (sizeSp * lineHeight), not as a raw TextView multiplier.
 *
 * Designed pairings (each set is a system):
 *   H5 + S5 + B5  Optical broadsheet, 1.25 scale (recommended)
 *   H6 + S6 + B6  Newsreader editorial, 1.25 scale (Jaryo pairing)
 *   H7 + S7 + B7  Perfect-fourth contrast, 1.333 scale
 *   H8 + S8 + B8  Quiet text-on-text, 1.2 scale
 */
final class TypeConfig {
    /** One of H1–H8. Recommended v2 default: H5. */
    static final String HEADER = "H5";
    /** One of S1–S8. Recommended v2 default: S5. */
    static final String SUBHEADER = "S5";
    /** One of B1–B8. Recommended v2 default: B5. */
    static final String BODY = "B5";

    static final String FACE_DISPLAY_BLACK = "displayBlack";
    static final String FACE_SUBHEAD_BOLD = "subheadBold";
    static final String FACE_SUBHEAD_SEMIBOLD = "subheadSemibold";
    static final String FACE_SM_TEXT_REGULAR = "smTextRegular";
    static final String FACE_SM_TEXT_BOLD = "smTextBold";
    static final String FACE_TEXT_REGULAR = "textRegular";
    static final String FACE_TEXT_SEMIBOLD = "textSemibold";
    static final String FACE_TEXT_ITALIC = "textItalic";
    static final String FACE_INTER_REGULAR = "interRegular";
    static final String FACE_INTER_MEDIUM = "interMedium";
    static final String FACE_INTER_SEMIBOLD = "interSemibold";
    static final String FACE_JETBRAINS_MONO_MEDIUM = "jetbrainsMonoMedium";
    static final String FACE_NEWSREADER_72_SEMIBOLD = "newsreader72Semibold";
    static final String FACE_NEWSREADER_16_REGULAR = "newsreader16Regular";
    static final String FACE_NEWSREADER_16_ITALIC = "newsreader16Italic";

    static final Map<String, Role> HEADERS = roles(
            /* Round 1, kept for rollback */
            role("H1", "Subhead 20", FACE_SUBHEAD_BOLD, 20, 17, 1.08f, 0f, false, false, ""),
            role("H2", "Display 22", FACE_DISPLAY_BLACK, 22, 18, 1.00f, -0.01f, false, false, ""),
            role("H3", "Text Bold 17", FACE_SM_TEXT_BOLD, 17, 15, 1.20f, 0f, false, false, ""),
            role("H4", "Sans Caps 20", FACE_INTER_SEMIBOLD, 20, 16, 1.10f, 0.06f, true, false, ""),
            /* Round 2 */
            role("H5", "Subhead Semi 21", FACE_SUBHEAD_SEMIBOLD, 21, 17, 1.15f, -0.01f, false, false, ""),
            role("H6", "Newsreader 22", FACE_NEWSREADER_72_SEMIBOLD, 22, 17, 1.18f, -0.012f, false, false, ""),
            role("H7", "Subhead Bold 22", FACE_SUBHEAD_BOLD, 22, 18, 1.12f, -0.02f, false, false, ""),
            role("H8", "Text Semi 20", FACE_TEXT_SEMIBOLD, 20, 16, 1.20f, -0.008f, false, false, "")
    );
    static final Map<String, Role> SUBHEADERS = roles(
            role("S1", "Inter Caps 11", FACE_INTER_SEMIBOLD, 11, 10, 1.15f, 0.08f, true, false, ""),
            role("S2", "Inter Soft 11", FACE_INTER_MEDIUM, 11, 10, 1.20f, 0f, false, false, ""),
            role("S3", "Serif 12", FACE_SM_TEXT_REGULAR, 12, 11, 1.25f, 0.02f, false, false, ""),
            role("S4", "Inter Caps 13", FACE_INTER_SEMIBOLD, 13, 11, 1.10f, 0.12f, true, false, ""),
            role("S5", "Inter 11 tnum", FACE_INTER_MEDIUM, 11, 10, 1.25f, 0.02f, true, true, FACE_JETBRAINS_MONO_MEDIUM),
            role("S6", "Inter 12 soft", FACE_INTER_REGULAR, 12, 10, 1.28f, 0.02f, false, true, FACE_JETBRAINS_MONO_MEDIUM),
            role("S7", "Inter 12 caps", FACE_INTER_MEDIUM, 12, 10, 1.22f, 0.05f, true, true, FACE_JETBRAINS_MONO_MEDIUM),
            role("S8", "Mono 11", FACE_JETBRAINS_MONO_MEDIUM, 11, 10, 1.30f, 0f, false, true, FACE_JETBRAINS_MONO_MEDIUM)
    );
    static final Map<String, Role> BODIES = roles(
            role("B1", "Text 18 / 1.35", FACE_SM_TEXT_REGULAR, 18, 15, 1.35f, 0f, false, false, ""),
            role("B2", "Compact 17 / 1.25", FACE_SM_TEXT_REGULAR, 17, 14, 1.25f, 0f, false, false, ""),
            role("B3", "Airy 18 / 1.50", FACE_SM_TEXT_REGULAR, 18, 15, 1.50f, 0.01f, false, false, ""),
            role("B4", "Sans 16 / 1.40", FACE_INTER_MEDIUM, 16, 14, 1.40f, 0f, false, false, ""),
            role("B5", "Text 17 / 1.35", FACE_TEXT_REGULAR, 17, 14, 1.35f, 0f, false, false, ""),
            role("B6", "Newsreader 17 / 1.45", FACE_NEWSREADER_16_REGULAR, 17, 14, 1.45f, 0f, false, false, ""),
            role("B7", "Text 16 / 1.38", FACE_TEXT_REGULAR, 16, 14, 1.38f, 0f, false, false, ""),
            role("B8", "Text 17 / 1.42", FACE_TEXT_REGULAR, 17, 14, 1.42f, 0.008f, false, false, "")
    );

    private TypeConfig() {}

    /**
     * A real bold cut for emphasis inside body text. Never ask Android to synthesize bold
     * (a smeared, glowing stroke); every face here is a bundled static cut.
     */
    static String emphasisFace(String bodyFace) {
        if (FACE_NEWSREADER_16_REGULAR.equals(bodyFace)) return FACE_NEWSREADER_72_SEMIBOLD;
        if (FACE_SM_TEXT_REGULAR.equals(bodyFace)) return FACE_SM_TEXT_BOLD;
        if (FACE_INTER_REGULAR.equals(bodyFace) || FACE_INTER_MEDIUM.equals(bodyFace)) {
            return FACE_INTER_SEMIBOLD;
        }
        return FACE_TEXT_SEMIBOLD;
    }

    /** A real italic cut; never a synthesized slant. */
    static String italicFace(String bodyFace) {
        if (FACE_NEWSREADER_16_REGULAR.equals(bodyFace)) return FACE_NEWSREADER_16_ITALIC;
        return FACE_TEXT_ITALIC;
    }

    static Role header() {
        return require(HEADERS, HEADER, "HEADER");
    }

    static Role subheader() {
        return require(SUBHEADERS, SUBHEADER, "SUBHEADER");
    }

    static Role body() {
        return require(BODIES, BODY, "BODY");
    }

    static Role header(String id) {
        return require(HEADERS, id, "header");
    }

    static Role subheader(String id) {
        return require(SUBHEADERS, id, "subheader");
    }

    static Role body(String id) {
        return require(BODIES, id, "body");
    }

    private static Role require(Map<String, Role> catalog, String id, String slot) {
        Role role = catalog.get(id);
        if (role == null) {
            throw new IllegalArgumentException("Unknown " + slot + " typography id: " + id);
        }
        return role;
    }

    private static Map<String, Role> roles(Role... list) {
        Map<String, Role> map = new LinkedHashMap<>();
        for (Role role : list) map.put(role.id, role);
        return map;
    }

    private static Role role(String id, String label, String face, int sizeSp, int coverSizeSp,
                             float lineHeight, float letterSpacing, boolean allCaps,
                             boolean tabular, String numeralFace) {
        return new Role(id, label, face, sizeSp, coverSizeSp, lineHeight, letterSpacing,
                allCaps, tabular, numeralFace == null ? "" : numeralFace);
    }

    /** One typographic treatment. Host-testable; no Android types. */
    static final class Role {
        final String id;
        final String label;
        final String face;
        final int sizeSp;
        final int coverSizeSp;
        final float lineHeight;
        final float letterSpacing;
        final boolean allCaps;
        final boolean tabular;
        /** Face for status, tok/s, and other numerals; empty means {@link #face}. */
        final String numeralFace;

        Role(String id, String label, String face, int sizeSp, int coverSizeSp,
             float lineHeight, float letterSpacing, boolean allCaps,
             boolean tabular, String numeralFace) {
            this.id = id;
            this.label = label;
            this.face = face;
            this.sizeSp = sizeSp;
            this.coverSizeSp = coverSizeSp;
            this.lineHeight = lineHeight;
            this.letterSpacing = letterSpacing;
            this.allCaps = allCaps;
            this.tabular = tabular;
            this.numeralFace = numeralFace;
        }

        int size(boolean cover) {
            return cover ? coverSizeSp : sizeSp;
        }

        String numerals() {
            return numeralFace.isEmpty() ? face : numeralFace;
        }

        String spec() {
            String tracking = letterSpacing == 0f ? "0"
                    : (letterSpacing > 0 ? "+" : "") + letterSpacing + "em";
            return face + " · " + sizeSp + "sp · " + lineHeight + " · tracking " + tracking
                    + (allCaps ? " · caps" : "")
                    + (tabular ? " · tnum" : "");
        }
    }
}

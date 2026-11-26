package os.opos.launcher;

public final class TypeConfigTest {
    public static void main(String[] args) {
        equal("H5", TypeConfig.HEADER);
        equal("S5", TypeConfig.SUBHEADER);
        equal("B5", TypeConfig.BODY);
        equal(8, TypeConfig.HEADERS.size());
        equal(8, TypeConfig.SUBHEADERS.size());
        equal(8, TypeConfig.BODIES.size());
        String[] headers = {"H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8"};
        String[] subs = {"S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"};
        String[] bodies = {"B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8"};
        for (String id : headers) {
            TypeConfig.Role role = TypeConfig.header(id);
            equal(id, role.id);
            check(role.sizeSp > 0 && role.coverSizeSp > 0);
            check(role.coverSizeSp <= role.sizeSp);
            check(role.lineHeight >= 1f);
            check(role.label != null && !role.label.isEmpty());
            check(role.face != null && !role.face.isEmpty());
        }
        for (String id : subs) {
            TypeConfig.Role role = TypeConfig.subheader(id);
            equal(id, role.id);
            check(role.sizeSp >= 10 && role.sizeSp <= 14);
            check(role.coverSizeSp <= role.sizeSp);
        }
        for (String id : bodies) {
            TypeConfig.Role role = TypeConfig.body(id);
            equal(id, role.id);
            check(role.sizeSp >= 16 && role.sizeSp <= 18);
            check(role.lineHeight >= 1.2f);
            check(!role.allCaps);
        }
        // Recommended v2 default: optical broadsheet, 1.25 scale (11 / 17 / 21).
        TypeConfig.Role header = TypeConfig.header();
        TypeConfig.Role sub = TypeConfig.subheader();
        TypeConfig.Role body = TypeConfig.body();
        equal("H5", header.id);
        equal(TypeConfig.FACE_SUBHEAD_SEMIBOLD, header.face);
        equal(21, header.sizeSp);
        equal(17, header.coverSizeSp);
        equal(1.15f, header.lineHeight);
        equal(-0.01f, header.letterSpacing);
        check(!header.allCaps);
        equal("S5", sub.id);
        equal(TypeConfig.FACE_INTER_MEDIUM, sub.face);
        equal(11, sub.sizeSp);
        equal(10, sub.coverSizeSp);
        equal(0.02f, sub.letterSpacing);
        check(sub.tabular);
        equal(TypeConfig.FACE_JETBRAINS_MONO_MEDIUM, sub.numerals());
        check(sub.allCaps);
        equal("B5", body.id);
        equal(TypeConfig.FACE_TEXT_REGULAR, body.face);
        equal(17, body.sizeSp);
        equal(14, body.coverSizeSp);
        equal(1.35f, body.lineHeight);
        check(header.sizeSp != sub.sizeSp);
        check(header.sizeSp != body.sizeSp);
        check(sub.sizeSp != body.sizeSp);
        // Modular 1.25 scale: 21/17 ≈ 1.235, 17/11 ≈ 1.545 (two steps 1.25^2=1.5625).
        check(Math.abs(header.sizeSp / (float) body.sizeSp - 1.25f) < 0.03f);
        check(Math.abs(body.sizeSp / (float) sub.sizeSp - 1.25f * 1.25f) < 0.08f);
        // v2 systems stay distinct from each other.
        check(!TypeConfig.header("H5").face.equals(TypeConfig.header("H6").face));
        check(!TypeConfig.body("B5").face.equals(TypeConfig.body("B6").face));
        check(TypeConfig.subheader("S5").tabular);
        check(TypeConfig.subheader("S8").face.equals(TypeConfig.FACE_JETBRAINS_MONO_MEDIUM));
        try {
            TypeConfig.header("H9");
            throw new AssertionError("expected unknown id");
        } catch (IllegalArgumentException ignored) {
        }
        System.out.println("TypeConfigTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }

    private static void equal(float expected, float actual) {
        if (Math.abs(expected - actual) > 0.0001f) throw new AssertionError(expected + " != " + actual);
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

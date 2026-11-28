package os.opos.launcher;

import java.util.Locale;

/**
 * Surface Duo hinge fallback table.
 */
final class DuoHingeTable {
    private DuoHingeTable() {
    }

    static SpanGeometry geometry(String manufacturer, String model, int windowW, int windowH) {
        if (!matchesMicrosoft(manufacturer)) {
            return SpanGeometry.NONE;
        }
        String normalizedModel = normalize(model);
        if ("surface duo".equals(normalizedModel)) {
            if (windowW == 2784 && windowH == 1800) {
                return SpanGeometry.of(windowW, windowH, 1350, 0, 1434, 1800);
            }
            return SpanGeometry.NONE;
        }
        if ("surface duo 2".equals(normalizedModel)) {
            if (windowW == 2754 && windowH == 1892) {
                return SpanGeometry.of(windowW, windowH, 1344, 0, 1410, 1892);
            }
        }
        return SpanGeometry.NONE;
    }

    private static boolean matchesMicrosoft(String manufacturer) {
        return "microsoft".equals(normalize(manufacturer));
    }

    private static String normalize(String value) {
        return value == null ? null : value.trim().toLowerCase(Locale.ROOT);
    }
}

package os.opos.launcher;

import java.nio.file.Files;
import java.nio.file.Path;

/** Host audit of cover view wiring; TalkBack and layout still need an installed phone check. */
public final class CoverStatusWiringTest {
    public static void main(String[] args) throws Exception {
        String source = Files.readString(Path.of(
                "app/src/main/java/os/opos/launcher/MainActivity.java"));
        String compact = between(source, "if (compactLayout) {", "updateCompactLaneStatus();");
        require(compact, "status.setAccessibilityLiveRegion(View.ACCESSIBILITY_LIVE_REGION_POLITE)");

        String cover = between(source, "private void applyCoverChrome()",
                "private void reserveCoverActionRow(");
        require(cover, "status.setMinLines(1)");
        require(cover, "coverTextHeight(status, 1)");
        require(cover, "coverTextHeight(status, 2)");
        require(cover, "status.setVisibility(View.VISIBLE)");
        require(cover, "status.setMaxLines(chrome.statusLines)");
        if (cover.contains("status.setVisibility(View.GONE)")) {
            throw new AssertionError("Cover connection announcement is hidden");
        }

        String measure = between(source, "private int coverTextHeight(",
                "private void reserveCoverActionRow(");
        require(measure, "StaticLayout.Builder.obtain");
        if (measure.contains("view.getHeight()") || measure.contains("view.getMeasuredHeight()")) {
            throw new AssertionError("Cover text height depends on a previous view layout");
        }
        System.out.println("CoverStatusWiringTest: OK");
    }

    private static String between(String source, String start, String end) {
        int from = source.indexOf(start);
        int to = source.indexOf(end, from + start.length());
        if (from < 0 || to < 0) throw new AssertionError("Method boundary missing: " + start);
        return source.substring(from, to);
    }

    private static void require(String source, String text) {
        if (!source.contains(text)) throw new AssertionError("Missing " + text);
    }
}

package os.opos.launcher;

import java.nio.file.Files;
import java.nio.file.Path;

/** Check the cover tokens and the Android calls that reapply them after screen selection. */
public final class SummaryTypographyTest {
    public static void main(String[] args) throws Exception {
        equal(21, TypeConfig.header().size(false));
        equal(17, TypeConfig.header().size(true));
        equal(17, TypeConfig.body().size(false));
        equal(14, TypeConfig.body().size(true));

        String source = Files.readString(Path.of(
                "app/src/main/java/os/opos/launcher/MainActivity.java"));
        String typography = section(source, "private void applyTypographyToPage()",
                "private void showSettings()");
        require(typography, "typography.headline(summaryHeading, typography.headingSp())");
        require(typography, "setSummaryReport(summaryText.getText().toString())");

        String cue = section(source, "private void setSummaryHeadingCue(boolean expanded)",
                "private void pinSummaryBar()");
        require(cue, "typography.labelSp()");
        require(cue, "summaryHeading.setText(heading)");
        require(source, "setSummaryHeadingCue(summaryExpanded)");
        require(source, "setSummaryHeadingCue(false)");

        String pageBar = section(source, "private LinearLayout pageBar(",
                "private void showFullPage(");
        require(pageBar, "newspaperText(title, typography.headingSp(), true, true)");
        System.out.println("SummaryTypographyTest: OK");
    }

    private static String section(String source, String startText, String endText) {
        int start = source.indexOf(startText);
        int end = source.indexOf(endText, start);
        if (start < 0 || end < 0) throw new AssertionError("Missing " + startText);
        return source.substring(start, end);
    }

    private static void require(String text, String phrase) {
        if (!text.contains(phrase)) throw new AssertionError("Missing " + phrase);
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

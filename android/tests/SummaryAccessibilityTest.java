package os.opos.launcher;

import java.nio.file.Files;
import java.nio.file.Path;

/** Host audit of Android view wiring; device TalkBack behavior still needs an install. */
public final class SummaryAccessibilityTest {
    public static void main(String[] args) throws Exception {
        String source = Files.readString(Path.of(
                "app/src/main/java/os/opos/launcher/MainActivity.java"));
        int start = source.indexOf("} else if (NotesSheet.summaryOpensFullPage(landscapeLayout)) {");
        int end = source.indexOf("if (summaryText != null)", start);
        if (start < 0 || end < 0) throw new AssertionError("Summary binding missing");
        String binding = source.substring(start, end);
        require(source, "summaryCard.addView(summaryText");
        require(binding, "summaryCard.setFocusable(false)");
        require(binding, "summaryCard.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO)");
        require(binding, "summaryHeading.setContentDescription(getString(R.string.summary_open))");
        require(binding, "summaryHeading.setAccessibilityDelegate(mastheadButtonRole())");
        require(binding, "summaryHeading.setOnClickListener(view -> showSummaryPage())");
        if (binding.contains("summaryCard.setContentDescription")) {
            throw new AssertionError("Card description hides the preview");
        }
        if (binding.contains("summaryText.setImportantForAccessibility")) {
            throw new AssertionError("Preview hidden from TalkBack");
        }
        System.out.println("SummaryAccessibilityTest: OK");
    }

    private static void require(String text, String phrase) {
        if (!text.contains(phrase)) throw new AssertionError("Missing " + phrase);
    }
}

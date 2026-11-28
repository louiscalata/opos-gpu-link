package os.opos.launcher;

/**
 * Display formatting and size policy for the "You asked:" question card.
 * Formatting is for on-screen copy only; callers must not send the display
 * string to the models.
 */
final class QuestionHeadline {
    /** A longer question can shrink below H5 to keep every word visible. */
    static final float LEADING = 1.25f;

    private QuestionHeadline() {}

    /** Length of the label to restyle, or 0 when the headline does not start with it. */
    static int prefixLength(String fullText, String prefix) {
        if (fullText == null || prefix == null || prefix.isEmpty()) return 0;
        return fullText.startsWith(prefix) ? prefix.length() : 0;
    }

    /**
     * Trim, collapse whitespace, sentence-case the first letter (leave the rest,
     * so acronyms like RAM stay intact), and add a trailing ? when the text
     * does not already end in ?, !, or a period.
     */
    static String displayQuestion(String raw) {
        if (raw == null) return "";
        String text = raw.trim().replaceAll("\\s+", " ");
        if (text.isEmpty()) return text;
        char first = text.charAt(0);
        if (Character.isLetter(first) && Character.isLowerCase(first)) {
            text = Character.toUpperCase(first) + text.substring(1);
        }
        char last = text.charAt(text.length() - 1);
        if (last != '?' && last != '!' && last != '.') {
            text = text + "?";
        }
        return text;
    }

    /** Prefix plus display-formatted body. {@code fullText} may already include the prefix. */
    static String formatHeadline(String fullText, String prefix) {
        String source = fullText == null ? "" : fullText;
        String body = source;
        int label = prefixLength(source, prefix);
        if (label > 0) body = source.substring(label);
        String shown = displayQuestion(body);
        if (prefix == null || prefix.isEmpty()) return shown;
        return prefix + shown;
    }

    static int baseSp(boolean coverMode) {
        return TypeConfig.header().size(coverMode);
    }

    static int minSp(boolean coverMode) {
        return TypeConfig.body().size(coverMode);
    }

    static int floorSp(boolean coverMode) {
        return TypeConfig.subheader().size(coverMode);
    }

    /**
     * Shrink from {@code currentSp} toward the floor when the text would
     * overflow {@code maxLines}. Returns the same size when it already fits.
     */
    static int shrinkSp(int currentSp, int floorSp, int lineCount, int maxLines) {
        if (lineCount <= maxLines) return currentSp;
        if (currentSp <= floorSp) return floorSp;
        return currentSp - 1;
    }

    /** Always at least two lines of room so a cover layout cannot crush the headline to a hairline. */
    static int minLines(boolean coverMode) {
        return 2;
    }

    static int maxLines(boolean coverMode) {
        return coverMode ? 4 : 6;
    }
}

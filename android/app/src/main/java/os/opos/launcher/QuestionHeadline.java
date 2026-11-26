package os.opos.launcher;

/** Decides how much of a headline is the small grey "You asked:" label. */
final class QuestionHeadline {
    private QuestionHeadline() {}

    /** Length of the label to restyle, or 0 when the headline does not start with it. */
    static int prefixLength(String fullText, String prefix) {
        if (fullText == null || prefix == null || prefix.isEmpty()) return 0;
        return fullText.startsWith(prefix) ? prefix.length() : 0;
    }

    /** Always at least two lines of room so a cover layout cannot crush the headline to a hairline. */
    static int minLines(boolean coverMode) {
        return 2;
    }

    static int maxLines(boolean coverMode) {
        return coverMode ? 3 : 4;
    }
}

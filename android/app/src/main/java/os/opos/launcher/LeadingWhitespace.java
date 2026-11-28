package os.opos.launcher;

/** Remove leading Unicode whitespace on Android 10 and newer. */
final class LeadingWhitespace {
    private LeadingWhitespace() {}

    /** Clear blank lines and prose padding without changing first-line structure. */
    static String stripAnswerStart(String value) {
        int lineStart = 0;
        while (lineStart < value.length()) {
            int start = lineStart;
            while (start < value.length()) {
                int codePoint = value.codePointAt(start);
                if (codePoint == '\n' || codePoint == '\r'
                        || !Character.isWhitespace(codePoint)) break;
                start += Character.charCount(codePoint);
            }
            if (start == value.length()) return "";
            if (value.charAt(start) == '\n' || value.charAt(start) == '\r') {
                lineStart = start + 1;
                if (value.charAt(start) == '\r' && lineStart < value.length()
                        && value.charAt(lineStart) == '\n') lineStart++;
                continue;
            }
            if (isCodeIndent(value, lineStart, start)
                    || (isListMarker(value, start) && start - lineStart >= 2)
                    || value.startsWith("```", start) || value.startsWith("~~~", start)) {
                return value.substring(lineStart);
            }
            return value.substring(start);
        }
        return "";
    }

    // A one-space list marker is not a list to AnswerMarkdownParser (one-space numbered
    // items are prose there), so it is trimmed to column 0 where it parses as a list.
    private static boolean isCodeIndent(String value, int lineStart, int start) {
        int spaces = 0;
        for (int i = lineStart; i < start;) {
            int codePoint = value.codePointAt(i);
            if (codePoint == '\t') return true;
            spaces++;
            i += Character.charCount(codePoint);
        }
        return spaces >= 4;
    }

    private static boolean isListMarker(String value, int start) {
        char marker = value.charAt(start);
        int end = start + 1;
        if (marker != '-' && marker != '*' && marker != '+') {
            if (!Character.isDigit(marker)) return false;
            while (end < value.length() && Character.isDigit(value.charAt(end))) end++;
            if (end == value.length() || value.charAt(end) != '.' && value.charAt(end) != ')') {
                return false;
            }
            end++;
        }
        return end < value.length() && (value.charAt(end) == ' ' || value.charAt(end) == '\t');
    }

    static String strip(String value) {
        int start = 0;
        while (start < value.length()) {
            int codePoint = value.codePointAt(start);
            if (!Character.isWhitespace(codePoint)) break;
            start += Character.charCount(codePoint);
        }
        return value.substring(start);
    }
}

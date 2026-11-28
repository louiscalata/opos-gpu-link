package os.opos.launcher;

/** Remove leading Unicode whitespace on Android 10 and newer. */
final class LeadingWhitespace {
    private LeadingWhitespace() {}

    /** Clear an answer's empty start, but keep indentation on a first list item. */
    static String stripAnswerStart(String value) {
        int start = 0;
        int lineStart = 0;
        while (start < value.length()) {
            int codePoint = value.codePointAt(start);
            if (!Character.isWhitespace(codePoint)) break;
            start += Character.charCount(codePoint);
            if (codePoint == '\n' || codePoint == '\r') lineStart = start;
        }
        if (start == value.length()) return "";
        int indent = start - lineStart;
        if (indent > 0 && indent <= 4 && isListMarker(value, start, indent)) {
            for (int i = lineStart; i < start; i++) {
                if (value.charAt(i) != ' ') return value.substring(start);
            }
            return value.substring(lineStart);
        }
        return value.substring(start);
    }

    private static boolean isListMarker(String value, int start, int indent) {
        char marker = value.charAt(start);
        int end = start + 1;
        if (marker != '-' && marker != '*' && marker != '+') {
            if (indent == 1 || !Character.isDigit(marker)) return false;
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

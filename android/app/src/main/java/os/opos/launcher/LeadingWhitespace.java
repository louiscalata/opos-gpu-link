package os.opos.launcher;

/** Remove leading Unicode whitespace on Android 10 and newer. */
final class LeadingWhitespace {
    private LeadingWhitespace() {}

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

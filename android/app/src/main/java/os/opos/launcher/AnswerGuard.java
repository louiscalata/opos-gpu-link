package os.opos.launcher;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Conservative text-shape checks, not a check that an answer is factually correct. */
final class AnswerGuard {
    /** UTF-16 characters; deliberately above an ordinary short demo answer. */
    static final int MAX_CHARS = 24_000;
    static final int TAIL_CHARS = 4_096;
    private static final int MAX_PERIOD = 64;
    private static final Pattern MOJIBAKE = Pattern.compile(
            "(?:\u00c3[\u0080-\u00bf]|\u00c2[\u0080-\u00bf]|"
                    + "\u00e2[\u0080-\u00bf\u2000-\u20ff]{1,2}|\u00f0\u0178)");
    private static final Pattern SPECIAL_TOKEN = Pattern.compile(
            "<\\|[A-Za-z0-9_./:-]{1,64}\\|>|<unused[0-9]{1,8}>");

    private AnswerGuard() {}

    /** Null means no evidence of garbage. Work is bounded by TAIL_CHARS * MAX_PERIOD. */
    static String reason(String text) {
        if (text == null || text.isEmpty()) return null;
        if (text.length() > MAX_CHARS) return "runaway_length";
        int start = Math.max(0, text.length() - TAIL_CHARS);
        if (start > 0 && Character.isLowSurrogate(text.charAt(start))) start++;
        String tail = text.substring(start);
        if (encodingJunk(tail)) return "encoding_junk";
        if (repeatedCharacter(tail)) return "repeat_char";
        if (repeatedFragment(tail)) return "ngram_loop";
        if (nonText(tail)) return "non_text";
        return null;
    }

    private static boolean encodingJunk(String text) {
        int replacements = 0;
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (c == 0) return true;
            replacements = c == '\ufffd' ? replacements + 1 : 0;
            if (replacements >= 3) return true;
        }
        if (MOJIBAKE.matcher(text).find()) return true;
        // One mention can be documentation or code; repeated leaked control tokens are evidence.
        Matcher tokens = SPECIAL_TOKEN.matcher(text);
        return tokens.find() && tokens.find();
    }

    private static boolean repeatedCharacter(String text) {
        int previous = -1;
        int run = 0;
        for (int i = 0; i < text.length();) {
            int c = text.codePointAt(i);
            i += Character.charCount(c);
            run = c == previous ? run + 1 : 1;
            previous = c;
            // Rules, fences, table separators, and whitespace are valid long runs.
            if (Character.isWhitespace(c) || "-_*=`~|".indexOf(c) >= 0) continue;
            int limit = Character.isLetter(c) ? 64 : 32;
            if (run >= limit) return true;
        }
        return false;
    }

    private static boolean repeatedFragment(String text) {
        for (int period = 2; period <= MAX_PERIOD && period * 8 <= text.length(); period++) {
            int matched = 0;
            int needed = Math.max(period * 8, 64) - period;
            for (int i = period; i < text.length(); i++) {
                matched = text.charAt(i) == text.charAt(i - period) ? matched + 1 : 0;
                if (matched == needed && hasWordCharacter(text, i - period + 1, i + 1)) {
                    return true;
                }
            }
        }
        return false;
    }

    private static boolean hasWordCharacter(String text, int start, int end) {
        for (int i = start; i < end;) {
            int c = text.codePointAt(i);
            if (Character.isLetterOrDigit(c)) return true;
            i += Character.charCount(c);
        }
        return false;
    }

    private static boolean nonText(String text) {
        int visible = 0;
        int noise = 0;
        boolean formattingOnly = true;
        for (int i = 0; i < text.length();) {
            int c = text.codePointAt(i);
            i += Character.charCount(c);
            if (Character.isWhitespace(c)) continue;
            if (Character.isLetterOrDigit(c)) return false;
            visible++;
            if (Character.isISOControl(c) || c == '\ufffd'
                    || Character.getType(c) == Character.OTHER_SYMBOL
                    || Character.getType(c) == Character.MATH_SYMBOL
                    || Character.getType(c) == Character.CURRENCY_SYMBOL
                    || Character.getType(c) == Character.MODIFIER_SYMBOL
                    || "@#$%^&!?/\\[]{}<>".indexOf(c) >= 0) noise++;
            if ("-_*=`~|:+.#".indexOf(c) < 0) formattingOnly = false;
        }
        return !formattingOnly && visible >= 96 && noise * 10 >= visible * 9;
    }
}

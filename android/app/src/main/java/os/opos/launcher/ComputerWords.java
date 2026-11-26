package os.opos.launcher;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Names the paired computer the way its owner would: a Mac is never called a "PC" on screen.
 * The noun follows the paired computer's display label, so a Windows or Linux PC still reads "PC".
 */
final class ComputerWords {
    static final String PC = "PC";
    private static final Pattern MACBOOK = Pattern.compile("(?i)\\bMacBook\\b");
    private static final Pattern MAC = Pattern.compile("(?i)\\b(iMac|Mac)\\b");
    private static final Pattern PC_WORD = Pattern.compile("\\bPC('s)?\\b");
    private static final Pattern PC_UPPER = Pattern.compile("\\bPC GPU EDITION\\b");

    private static volatile String current = PC;

    private ComputerWords() {}

    /** The noun for a computer label: "MacBook", "Mac" or "PC". */
    static String noun(String label) {
        if (label == null) return PC;
        if (MACBOOK.matcher(label).find()) return "MacBook";
        if (MAC.matcher(label).find()) return "Mac";
        return PC;
    }

    static String current() {
        return current;
    }

    /** Remember the paired computer's noun; returns true when it changed. */
    static boolean observe(String label) {
        if (label == null || label.trim().isEmpty()) return false;
        return set(noun(label));
    }

    static boolean set(String noun) {
        String next = "MacBook".equals(noun) || "Mac".equals(noun) ? noun : PC;
        if (next.equals(current)) return false;
        current = next;
        return true;
    }

    static String apply(String text) {
        return apply(text, current);
    }

    /** Replace the standalone word "PC" (and "PC's") with the noun; other words are untouched. */
    static String apply(String text, String noun) {
        if (text == null || PC.equals(noun) || text.indexOf("PC") < 0) return text;
        String upper = PC_UPPER.matcher(text).replaceAll(noun.toUpperCase(Locale.US) + " GPU EDITION");
        Matcher m = PC_WORD.matcher(upper);
        StringBuffer out = new StringBuffer();
        while (m.find()) {
            m.appendReplacement(out, Matcher.quoteReplacement(noun + (m.group(1) == null ? "" : "'s")));
        }
        m.appendTail(out);
        return out.toString();
    }
}

package os.opos.launcher;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Names the paired computer the way its owner would: a Mac is never called a "PC" on screen.
 * The noun follows the paired computer's display label, so a Windows or Linux PC still reads "PC".
 * With no paired computer the neutral "computer" is used, capitalised where it starts a line.
 */
final class ComputerWords {
    static final String PC = "PC";
    static final String COMPUTER = "computer";
    private static final Pattern MACBOOK = Pattern.compile("(?i)\\b(MacBook|MBP(?![A-Za-z]))");
    private static final Pattern MAC = Pattern.compile("(?i)\\b(iMac|Mac(?:intosh|mini|Studio|Pro)?)(?![A-Za-z])");
    private static final Pattern PC_WORD = Pattern.compile("\\bPC('s)?\\b");
    private static final Pattern PC_UPPER = Pattern.compile("\\bPC GPU EDITION\\b");
    private static final Pattern SENTENCE_END = Pattern.compile("(^[\\s\u00a0]*|[.!?:][\\s\u00a0]+|[\u00b7\u2014(][\\s\u00a0]*|\\n[\\s\u00a0]*)$");

    private static volatile String current = COMPUTER;

    private ComputerWords() {}

    /** The noun for a computer label: "MacBook", "Mac", "PC", or "computer" when there is no label. */
    static String noun(String label) {
        if (label == null || label.trim().isEmpty()) return COMPUTER;
        if (MACBOOK.matcher(label).find()) return "MacBook";
        if (MAC.matcher(label).find()) return "Mac";
        return PC;
    }

    static String current() {
        return current;
    }

    /** The noun as a standalone label, such as a TONIGHT row: "Computer", "MacBook", "Mac" or "PC". */
    static String title(String noun) {
        if (noun == null || noun.isEmpty()) return "Computer";
        return Character.toUpperCase(noun.charAt(0)) + noun.substring(1);
    }

    /** Remember the paired computer's noun; returns true when it changed. */
    static boolean observe(String label) {
        if (label == null || label.trim().isEmpty()) return false;
        return set(noun(label));
    }

    /** The saved noun from an earlier start. "PC" was also the old unpaired default, so it restarts
     *  neutral; a paired PC is named again by the first snapshot. */
    static boolean restore(String saved) {
        return set(PC.equals(saved) ? COMPUTER : saved);
    }

    static synchronized boolean set(String noun) {
        String next = "MacBook".equals(noun) || "Mac".equals(noun) || PC.equals(noun) ? noun : COMPUTER;
        if (next.equals(current)) return false;
        current = next;
        return true;
    }

    static String apply(String text) {
        return apply(text, current);
    }

    /** Replace the standalone word "PC" (and "PC's") with the noun; other words are untouched. */
    static String apply(String text, String noun) {
        if (text == null || noun == null || PC.equals(noun) || text.indexOf("PC") < 0) return text;
        String upper = PC_UPPER.matcher(text).replaceAll(noun.toUpperCase(Locale.US) + " GPU EDITION");
        Matcher m = PC_WORD.matcher(upper);
        StringBuffer out = new StringBuffer();
        while (m.find()) {
            String word = SENTENCE_END.matcher(upper.substring(0, m.start())).find() ? title(noun) : noun;
            m.appendReplacement(out, Matcher.quoteReplacement(word + (m.group(1) == null ? "" : "'s")));
        }
        m.appendTail(out);
        return out.toString();
    }
}

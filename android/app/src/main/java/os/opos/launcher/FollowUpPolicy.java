package os.opos.launcher;

import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/**
 * Retry and "again" must resend the original question. The models keep no chat history, so
 * a bare "again" sent on its own gets answers like "it seems you want to repeat a previous
 * task". A bare follow-up in the composer is turned back into the last real question.
 */
final class FollowUpPolicy {
    private static final Set<String> BARE = new HashSet<>(Arrays.asList(
            "again", "retry", "try again", "redo", "repeat", "do it again", "do that again",
            "run it again", "run that again", "ask again", "ask them again", "once more",
            "one more time", "same again", "same question", "same question again",
            "resend", "re-send", "rerun", "re-run", "refresh", "regenerate",
            "try that again", "try it again", "retry that", "please try again",
            "please retry", "please repeat", "repeat that", "repeat the question"));

    private FollowUpPolicy() {}

    static boolean bareFollowUp(String text) {
        return BARE.contains(normalize(text));
    }

    /** The text to send for a Send tap: the original question when the typed text is a bare follow-up. */
    static String resolve(String typed, String previousQuestion) {
        String text = typed == null ? "" : typed.trim();
        if (!bareFollowUp(text)) return text;
        String previous = previousQuestion == null ? "" : previousQuestion.trim();
        return previous.isEmpty() || bareFollowUp(previous) ? text : previous;
    }

    /** The question a Retry or Try again button resends: never blank, never a bare follow-up when avoidable. */
    static String originalQuestion(String shownQuestion, String lastSubmitted) {
        String shown = shownQuestion == null ? "" : shownQuestion.trim();
        String last = lastSubmitted == null ? "" : lastSubmitted.trim();
        if (!shown.isEmpty() && !bareFollowUp(shown)) return shown;
        if (!last.isEmpty() && !bareFollowUp(last)) return last;
        return shown.isEmpty() ? last : shown;
    }

    private static String normalize(String text) {
        if (text == null) return "";
        String lower = text.toLowerCase(Locale.ROOT).trim();
        StringBuilder out = new StringBuilder();
        boolean space = false;
        for (int i = 0; i < lower.length(); i++) {
            char c = lower.charAt(i);
            if (Character.isLetterOrDigit(c) || c == '-') {
                if (space && out.length() > 0) out.append(' ');
                space = false;
                out.append(c);
            } else if (Character.isWhitespace(c) || c == ',' || c == '.' || c == '!' || c == '?'
                    || c == '\'' || c == '\u2019') {
                space = c != '\'' && c != '\u2019' ? true : space;
            } else {
                return "";
            }
        }
        return out.toString();
    }
}

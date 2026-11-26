package os.opos.launcher;

/**
 * Hide phone models that failed the offline phone-model validator
 * (receipts in gpulink-guard-work/receipts/validator-phone-models, 25 Nov 2026).
 * The live snapshot still advertises them with ready=true; the app must not list
 * them as lanes. Failed models are hidden, not merely marked.
 */
final class PhoneModelGate {
    private PhoneModelGate() {}

    static boolean hidden(String... labels) {
        String normalized = normalize(join(labels));
        if (normalized.isEmpty()) return false;
        if (isQwen3_4b(normalized)) return true;
        if (normalized.contains("muse glimmer")) return true;
        return false;
    }

    /** "Qwen3 4B", "qwen3-4b", "qwen/qwen3-4b" — not Qwen2.5, not Qwen3.8 27B. */
    static boolean isQwen3_4b(String normalized) {
        return containsWord(normalized, "qwen3 4b") || containsWord(normalized, "qwen 3 4b");
    }

    static String normalize(String text) {
        if (text == null) return "";
        StringBuilder out = new StringBuilder();
        boolean space = false;
        for (int i = 0; i < text.length(); i++) {
            char c = Character.toLowerCase(text.charAt(i));
            if (c == '.' || c == '_' || c == '-' || c == '/' || c == ',') c = ' ';
            if (Character.isLetterOrDigit(c)) {
                if (space && out.length() > 0) out.append(' ');
                space = false;
                out.append(c);
            } else if (Character.isWhitespace(c)) {
                space = true;
            }
        }
        return out.toString();
    }

    private static String join(String... labels) {
        if (labels == null) return "";
        StringBuilder out = new StringBuilder();
        for (String label : labels) {
            if (label == null || label.isEmpty()) continue;
            if (out.length() > 0) out.append(' ');
            out.append(label);
        }
        return out.toString();
    }

    private static boolean containsWord(String haystack, String phrase) {
        int at = haystack.indexOf(phrase);
        while (at >= 0) {
            boolean startOk = at == 0 || haystack.charAt(at - 1) == ' ';
            int end = at + phrase.length();
            boolean endOk = end == haystack.length() || haystack.charAt(end) == ' ';
            if (startOk && endOk) return true;
            at = haystack.indexOf(phrase, at + 1);
        }
        return false;
    }
}

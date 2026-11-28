package os.opos.launcher;

import java.util.Locale;
import java.util.regex.Pattern;

/**
 * The maker shown on a Model Selection row. Host-testable; no Android types. When the phone
 * service does not report a maker, a known model family names it (the NVIDIA models are
 * Nemotron and AceInstruct); otherwise the maker is left out rather than shown as
 * "Maker unavailable". A maker already in the model name is not repeated.
 */
final class ModelMaker {
    static final String NVIDIA = "NVIDIA";
    private static final Pattern NVIDIA_WORD = Pattern.compile("(?<![a-z0-9])nvidia(?![a-z0-9])");

    private ModelMaker() {}

    /** The known model family takes priority; otherwise use the reported maker. */
    static String maker(String reported, String model) {
        String r = reported == null ? "" : reported.trim();
        String m = model == null ? "" : model.toLowerCase(Locale.US);
        if (m.contains("nemotron") || m.contains("aceinstruct")
                || NVIDIA_WORD.matcher(m).find()) {
            return NVIDIA;
        }
        if (m.contains("lfm")) return "Liquid AI";
        if (m.contains("qwen")) return "Qwen (Alibaba)";
        if (m.contains("granite")) return "IBM";
        return r;
    }

    /** "Nemotron Mini 4B · NVIDIA · on this phone"; the maker is skipped when empty or already named. */
    static String details(String model, String maker, String where) {
        String m = ModelDisplay.label(model);
        String k = maker == null ? "" : maker.trim();
        String w = where == null ? "" : where.trim();
        StringBuilder sb = new StringBuilder();
        if (!m.isEmpty()) sb.append(m);
        boolean named = !k.isEmpty() && m.toLowerCase(Locale.US).contains(k.toLowerCase(Locale.US));
        if (!k.isEmpty() && !named) {
            if (sb.length() > 0) sb.append(" · ");
            sb.append(k);
        }
        if (!w.isEmpty()) {
            if (sb.length() > 0) sb.append(" · ");
            sb.append(w);
        }
        return sb.toString();
    }
}

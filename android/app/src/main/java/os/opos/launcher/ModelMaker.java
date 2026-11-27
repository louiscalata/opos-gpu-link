package os.opos.launcher;

import java.util.Locale;

/**
 * The maker shown on a Model Selection row. Host-testable; no Android types. When the phone
 * service does not report a maker, a known model family names it (the NVIDIA models are
 * Nemotron and AceInstruct); otherwise the maker is left out rather than shown as
 * "Maker unavailable". A maker already in the model name is not repeated.
 */
final class ModelMaker {
    static final String NVIDIA = "NVIDIA";

    private ModelMaker() {}

    /** The reported maker, else one inferred from the model name, else "". */
    static String maker(String reported, String model) {
        String r = reported == null ? "" : reported.trim();
        if (!r.isEmpty()) return r;
        String m = model == null ? "" : model.toLowerCase(Locale.US);
        if (m.contains("nvidia") || m.contains("nemotron") || m.contains("aceinstruct")) {
            return NVIDIA;
        }
        if (m.contains("lfm")) return "Liquid AI";
        return "";
    }

    /** "Nemotron Mini 4B · NVIDIA · on this phone"; the maker is skipped when empty or already named. */
    static String details(String model, String maker, String where) {
        String m = model == null ? "" : model.trim();
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

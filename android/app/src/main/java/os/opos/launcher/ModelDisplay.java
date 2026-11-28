package os.opos.launcher;

import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Names only model identities that the shipped sources establish. Other names stay as reported. */
final class ModelDisplay {
    private static final Pattern BOLT = Pattern.compile(
            "(?i)(?<![a-z0-9])nemotron[-_ ]3\\.5[-_ ]bolt(?=$|[^a-z0-9])");
    private static final Pattern LFM2 = Pattern.compile(
            "(?i)(?<![a-z0-9])lfm2(?:[-_ ](\\d+(?:\\.\\d+)?[bm]))?(?=$|[^a-z0-9.])");
    private static final Pattern QWEN = Pattern.compile(
            "(?i)(?<![a-z0-9])qwen[-_]?3\\.5[-_ ]2b(?=$|[^a-z0-9])");
    private static final Pattern GRANITE = Pattern.compile(
            "(?i)(?<![a-z0-9])granite[-_ ]4\\.1[-_ ]3b(?=$|[^a-z0-9])");

    private ModelDisplay() {}

    static String label(String reported) {
        String name = reported == null ? "" : reported.trim();
        if (BOLT.matcher(name).find()) return "Nemotron 3.5 Bolt";
        Matcher lfm = LFM2.matcher(name);
        if (lfm.find()) {
            String size = lfm.group(1);
            if (size != null) return "LFM2 " + size.toUpperCase(Locale.US) + " (baseline)";
            if (name.equalsIgnoreCase("LFM2") || name.equalsIgnoreCase("LFM2 (baseline)")) {
                return "LFM2 (baseline)";
            }
            return name.toLowerCase(Locale.US).contains("baseline")
                    ? name : name + " (baseline)";
        }
        if (QWEN.matcher(name).find()) return "Qwen3.5-2B";
        if (GRANITE.matcher(name).find()) return "Granite 4.1 3B";
        return name;
    }

    static String firstNonBlank(String preferred, String fallback) {
        String first = preferred == null ? "" : preferred.trim();
        return first.isEmpty() ? fallback == null ? "" : fallback.trim() : first;
    }
}

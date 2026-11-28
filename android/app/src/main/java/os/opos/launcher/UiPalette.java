package os.opos.launcher;

import java.util.Arrays;
import java.util.Collections;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * The only colours the UI may use: black, white, gray strokes, red for errors
 * and green for success. One class is the source of truth for both themes.
 * Never use colour alone; status text stays on the label.
 */
final class UiPalette {
    enum Theme { DARK, LIGHT }
    /**
     * PAUSED is a planned pause (cable out, the computer catches up later): ink, never red,
     * so pulling the cable on stage does not read as a failure. Lanes show it as an
     * inverted chip and a full-ink wall.
     */
    enum Tone { NEUTRAL, ERROR, OK, PAUSED }

    static final String BLACK = "#000000";
    static final String WHITE = "#FFFFFF";
    static final String STROKE = "#5C5C5C";
    static final String LABEL_DARK = "#BFBFBF";
    static final String LABEL_LIGHT = "#5C5C5C";
    /** ~#FF5A52, 6.84:1 on black. */
    static final String ERROR_DARK = "#FF5A52";
    /** Same red family, 6.54:1 on white. */
    static final String ERROR_LIGHT = "#B3261E";
    /** ~#3DDC84, 11.77:1 on black. */
    static final String OK_DARK = "#3DDC84";
    /** Same green family, 5.40:1 on white. */
    static final String OK_LIGHT = "#0F7A45";

    static final float MIN_TEXT_CONTRAST = 4.5f;
    static final float MIN_STROKE_CONTRAST = 3.0f;

    static final Set<String> CHROMATIC = Collections.unmodifiableSet(new LinkedHashSet<>(
            Arrays.asList(ERROR_DARK, ERROR_LIGHT, OK_DARK, OK_LIGHT)));

    final Theme theme;

    UiPalette(Theme theme) {
        this.theme = theme == null ? Theme.DARK : theme;
    }

    static Theme resolve(String preference, boolean systemDark) {
        if ("light".equals(preference)) return Theme.LIGHT;
        if ("system".equals(preference)) return systemDark ? Theme.DARK : Theme.LIGHT;
        return Theme.DARK;
    }

    boolean light() { return theme == Theme.LIGHT; }

    /** Android's light system-bar appearance means dark icons on light paper. */
    boolean darkSystemBarIcons() { return light(); }

    String paper() { return light() ? WHITE : BLACK; }
    String ink() { return light() ? BLACK : WHITE; }
    String selectionFill(boolean on) { return on ? ink() : paper(); }
    String selectionText(boolean on) { return on ? paper() : ink(); }
    String stroke() { return STROKE; }
    String label() { return light() ? LABEL_LIGHT : LABEL_DARK; }
    String error() { return light() ? ERROR_LIGHT : ERROR_DARK; }
    String ok() { return light() ? OK_LIGHT : OK_DARK; }

    String colorForTone(Tone tone) {
        if (tone == Tone.ERROR) return error();
        if (tone == Tone.OK) return ok();
        return ink();
    }

    /** An errored card turns its wall red, a paused one full ink; success stays a quiet gray. */
    String cardStroke(Tone tone) {
        if (tone == Tone.ERROR) return error();
        if (tone == Tone.PAUSED) return ink();
        return stroke();
    }

    static Tone tone(CharSequence text) {
        if (text == null) return Tone.NEUTRAL;
        String lower = text.toString().trim().toLowerCase(Locale.US);
        if (lower.isEmpty()) return Tone.NEUTRAL;
        // Ignore the planned cable event itself, but still inspect what follows it.
        if (lower.startsWith("usb cable disconnected")) lower = lower.substring(22);
        else if (lower.startsWith("usb disconnected")) lower = lower.substring(16);
        else if (lower.startsWith("cable out")) lower = lower.substring(9);
        // A user-requested Stop is a neutral end state, including its elapsed time.
        if (lower.equals("stopped") || lower.startsWith("stopped ·")) return Tone.NEUTRAL;
        // Hard errors first, so "Paused — stuck" stays red; a plain pause is ink.
        if (containsAny(lower, "garbled", "stuck", "failed", "failure",
                "disconnected", "unreachable", "unavailable",
                "validator", "invalid", "stale snapshot", "expired", "could not",
                "stopped early", "not enough free memory", "taking too long")
                || hasWord(lower, "stopped")) {
            return Tone.ERROR;
        }
        if (lower.contains("error")) return Tone.ERROR;
        // These are ordinary waiting states, even with a model name or cable prefix.
        if (lower.contains("not connected") || lower.contains("not ready")) return Tone.NEUTRAL;
        if (hasWord(lower, "paused")) return Tone.PAUSED;
        if (lower.contains("getting ready") || lower.contains("getting the pc")) {
            return Tone.NEUTRAL;
        }
        if (lower.startsWith("done") || "done".equals(lower) || lower.contains("· done")
                || lower.endsWith(" done")) {
            return Tone.OK;
        }
        if (hasWord(lower, "ready")) return Tone.OK;
        if (lower.contains("finished")) return Tone.OK;
        if (hasWord(lower, "connected")) return Tone.OK;
        return Tone.NEUTRAL;
    }

    static Tone toneFromStatus(String status, boolean garbled) {
        if (garbled) return Tone.ERROR;
        if (status == null) return Tone.NEUTRAL;
        switch (status) {
            case "FAILED":
            case "STUCK":
            case "failed":
            case "stuck":
            case "garbled":
                return Tone.ERROR;
            // A planned cable pause is ink, never red (same rule as the lane chip).
            case "PAUSED":
            case "paused":
                return Tone.PAUSED;
            case "DONE":
            case "done":
                return Tone.OK;
            default:
                return tone(status);
        }
    }

    static boolean retryAppliesToError(Tone tone) {
        return tone == Tone.ERROR;
    }

    static double contrast(String a, String b) {
        double la = luminance(a);
        double lb = luminance(b);
        double hi = Math.max(la, lb);
        double lo = Math.min(la, lb);
        return (hi + 0.05) / (lo + 0.05);
    }

    static double luminance(String hex) {
        int rgb = rgb(hex);
        return 0.2126 * linear((rgb >> 16) & 0xFF)
                + 0.7152 * linear((rgb >> 8) & 0xFF)
                + 0.0722 * linear(rgb & 0xFF);
    }

    /** 0x00RRGGBB of a #RGB, #RRGGBB or #AARRGGBB value. */
    static int rgb(String hex) {
        int[] parts = parts(hex);
        return (parts[1] << 16) | (parts[2] << 8) | parts[3];
    }

    static int argb(String hex) {
        int[] parts = parts(hex);
        return (parts[0] << 24) | (parts[1] << 16) | (parts[2] << 8) | parts[3];
    }

    static boolean isGray(String hex) {
        int rgb = rgb(hex);
        int r = (rgb >> 16) & 0xFF;
        int g = (rgb >> 8) & 0xFF;
        int b = rgb & 0xFF;
        return r == g && g == b;
    }

    static boolean allowedHex(String hex) {
        String normalized = normalize(hex);
        if (normalized == null) return false;
        String rgbHex = "#" + normalized.substring(2);
        if (isGray(rgbHex)) return true;
        for (String allowed : CHROMATIC) {
            if (rgbHex.equalsIgnoreCase(allowed)) return true;
        }
        return false;
    }

    static String normalize(String hex) {
        if (hex == null) return null;
        String value = hex.trim();
        if (value.startsWith("#")) value = value.substring(1);
        if (value.length() == 3) {
            value = "" + value.charAt(0) + value.charAt(0)
                    + value.charAt(1) + value.charAt(1)
                    + value.charAt(2) + value.charAt(2);
        }
        if (value.length() == 6) value = "FF" + value;
        if (value.length() != 8) return null;
        try {
            Long.parseLong(value, 16);
        } catch (NumberFormatException bad) {
            return null;
        }
        return value.toUpperCase(Locale.US);
    }

    static final Pattern HEX = Pattern.compile("#[0-9A-Fa-f]{3,8}\\b");

    static Matcher hexMatcher(String source) {
        return Pattern.compile("#[0-9A-Fa-f]{3,8}\\b").matcher(source);
    }

    static Set<String> allowedLiterals() {
        return Collections.unmodifiableSet(new LinkedHashSet<>(Arrays.asList(
                BLACK, WHITE, STROKE, LABEL_DARK, LABEL_LIGHT,
                ERROR_DARK, ERROR_LIGHT, OK_DARK, OK_LIGHT)));
    }

    private static boolean containsAny(String lower, String... needles) {
        for (String needle : needles) if (lower.contains(needle)) return true;
        return false;
    }

    private static boolean hasWord(String lower, String word) {
        Matcher matcher = Pattern.compile("\\b" + Pattern.quote(word) + "\\b").matcher(lower);
        return matcher.find();
    }

    private static double linear(int channel) {
        double c = channel / 255.0;
        return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
    }

    private static int[] parts(String hex) {
        String normalized = normalize(hex);
        if (normalized == null) throw new IllegalArgumentException("Bad color: " + hex);
        return new int[]{
                Integer.parseInt(normalized.substring(0, 2), 16),
                Integer.parseInt(normalized.substring(2, 4), 16),
                Integer.parseInt(normalized.substring(4, 6), 16),
                Integer.parseInt(normalized.substring(6, 8), 16)
        };
    }

    private static String normalizedToRgb(String normalized) {
        return "#" + normalized.substring(2);
    }
}

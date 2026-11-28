package os.opos.launcher;

/**
 * The phone heat meter in the masthead, from Android's thermal status (PowerManager 0..6:
 * none, light, moderate, severe, critical, emergency, shutdown). Host-testable; no Android
 * types. Cool (0–1) uses success green, warm (2) uses ink, and hot (3–6) uses error red.
 */
final class HeatMeter {
    private HeatMeter() {}

    /** A status Android actually reports; anything else hides the meter. */
    static boolean known(int status) { return status >= 0 && status <= 6; }

    /** The two ordinary, cool statuses. */
    static boolean cool(int status) { return status >= 0 && status <= 1; }

    /** Red only when Android reports hot or worse. */
    static boolean hot(int status) { return status >= 3 && status <= 6; }

    /** The same heat state uses the same palette tone in every layout and theme. */
    static UiPalette.Tone tone(int status) {
        if (cool(status)) return UiPalette.Tone.OK;
        if (hot(status)) return UiPalette.Tone.ERROR;
        return UiPalette.Tone.NEUTRAL;
    }

    static String word(int status) {
        switch (status) {
            case 0: case 1: return "cool";
            case 2: return "warm";
            case 3: return "hot";
            case 4: return "very hot";
            case 5: case 6: return "too hot";
            default: return "";
        }
    }

    /**
     * Words first, readable from a stage: "● Phone warm"; compact (cover screen) "● warm".
     * TalkBack reads the same plain heat word. Unknown: "".
     */
    static String label(int status, boolean compact) {
        if (!known(status)) return "";
        return compact ? "● " + word(status) : "● Phone " + word(status);
    }

    /** For TalkBack: "Phone is warm". Unknown: "". */
    static String description(int status) {
        return known(status) ? "Phone is " + word(status) : "";
    }
}

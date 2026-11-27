package os.opos.launcher;

/**
 * The phone heat meter in the masthead, from Android's thermal status (PowerManager 0..6:
 * none, light, moderate, severe, critical, emergency, shutdown). Host-testable; no Android
 * types. Two colours only: green while cool (0–1), red from warm (2) up. No middle colour.
 */
final class HeatMeter {
    private HeatMeter() {}

    /** A status Android actually reports; anything else hides the meter. */
    static boolean known(int status) { return status >= 0 && status <= 6; }

    /** Green for 0–1; every other known status is red. */
    static boolean cool(int status) { return status >= 0 && status <= 1; }

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
     * Android's raw status number stays in the TalkBack description. Unknown: "".
     */
    static String label(int status, boolean compact) {
        if (!known(status)) return "";
        return compact ? "● " + word(status) : "● Phone " + word(status);
    }

    /** Masthead size in sp: larger than the 13 sp status line so the room can read it. */
    static final int TEXT_SP = 16;
    static final int TEXT_SP_COMPACT = 14;

    /** For TalkBack: "Phone heat 2, warm". Unknown: "". */
    static String description(int status) {
        return known(status) ? "Phone heat " + status + ", " + word(status) : "";
    }
}

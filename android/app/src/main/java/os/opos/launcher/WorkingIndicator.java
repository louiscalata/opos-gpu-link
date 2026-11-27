package os.opos.launcher;

/**
 * The green "working" line under a lane that is streaming or thinking. Host-testable; no
 * Android types. It shows only for the exact live lane labels, so it disappears the moment a
 * lane is done, paused, stopped or failed.
 */
final class WorkingIndicator {
    /** About 6–7 frames a second: visibly alive from the stage, light on battery. */
    static final long TICK_MS = 150L;
    /** A rising and falling bar. Every glyph is in the bundled JetBrains Mono. */
    static final String SPINNER = "▁▂▃▄▅▆▇█▇▆▅▄▃▂";

    private WorkingIndicator() {}

    static final String STREAMING = "Streaming…";
    static final String THINKING = "Thinking…";

    /** True only for the exact live lane labels "Streaming…" and "Thinking…". */
    static boolean working(CharSequence stateWords) {
        if (stateWords == null) return false;
        String s = stateWords.toString().trim();
        return STREAMING.equals(s) || THINKING.equals(s);
    }

    /**
     * "● ▃ Working… · 312 words"; with reduced motion "● Working… · 312 words". Compact (cover
     * screen, narrow columns) drops "Working…" once words arrive: "● ▃ 312 words".
     */
    static String line(long tick, int words, boolean reducedMotion, boolean compact) {
        int w = Math.max(0, words);
        StringBuilder sb = new StringBuilder("● ");
        if (!reducedMotion) sb.append(SPINNER.charAt(index(tick, SPINNER.length()))).append(' ');
        if (w > 0 && compact) return sb.append(w).append(w == 1 ? " word" : " words").toString();
        sb.append("Working…");
        if (w > 0) sb.append(" · ").append(w).append(w == 1 ? " word" : " words");
        return sb.toString();
    }

    /** The dot pulses about once a second (bright 4 ticks, dim 4); steady with reduced motion. */
    static boolean dotBright(long tick, boolean reducedMotion) {
        return reducedMotion || index(tick, 8) < 4;
    }

    /** floorMod for a long tick without the API 31 Math.floorMod(long, int) overload. */
    private static int index(long tick, int n) {
        return (int) Math.floorMod(tick, (long) n);
    }
}

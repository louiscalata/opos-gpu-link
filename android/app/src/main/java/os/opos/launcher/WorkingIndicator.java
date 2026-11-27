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

    /** True only for the live lane labels "Streaming…" and "Thinking…". */
    static boolean working(CharSequence stateWords) {
        if (stateWords == null) return false;
        String s = stateWords.toString().trim();
        return s.startsWith("Streaming") || s.startsWith("Thinking");
    }

    /** "● ▃ Working… · 312 words"; with reduced motion "● Working… · 312 words". */
    static String line(long tick, int words, boolean reducedMotion) {
        int w = Math.max(0, words);
        StringBuilder sb = new StringBuilder("● ");
        if (reducedMotion) sb.append("Working…");
        else sb.append(SPINNER.charAt(Math.floorMod(tick, SPINNER.length()))).append(" Working…");
        if (w > 0) sb.append(" · ").append(w).append(w == 1 ? " word" : " words");
        return sb.toString();
    }

    /** The dot pulses about once a second (bright 4 ticks, dim 4); steady with reduced motion. */
    static boolean dotBright(long tick, boolean reducedMotion) {
        return reducedMotion || Math.floorMod(tick, 8) < 4;
    }
}

package os.opos.launcher;

/**
 * The green live state line for a lane that is streaming or thinking. Host-testable; no
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
        String s = label(stateWords);
        return STREAMING.equals(s) || THINKING.equals(s);
    }

    /** Keep the card's one visible line in step with its plain state and word count. */
    static String line(long tick, CharSequence stateWords, int words, boolean reducedMotion) {
        String state = label(stateWords);
        if (state.isEmpty()) return "";
        int w = Math.max(0, words);
        StringBuilder sb = new StringBuilder("● ");
        if (!reducedMotion) sb.append(SPINNER.charAt(index(tick, SPINNER.length()))).append(' ');
        sb.append(state);
        if (w > 0) sb.append(" · ").append(w).append(w == 1 ? " word" : " words");
        return sb.toString();
    }

    /** A spoken label without the moving dot or bar. */
    static String spoken(CharSequence stateWords, int words) {
        String state = label(stateWords).replace("…", "").trim();
        if (state.isEmpty()) return "";
        int count = Math.max(0, words);
        return count == 0 ? state : state + ", " + count
                + (count == 1 ? " word" : " words");
    }

    private static String label(CharSequence stateWords) {
        return stateWords == null ? "" : stateWords.toString().trim();
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

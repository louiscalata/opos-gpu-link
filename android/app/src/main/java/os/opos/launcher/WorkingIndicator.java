package os.opos.launcher;

/** The live card label and motion, with no Android types so the frames can be host-tested. */
final class WorkingIndicator {
    static final long CYCLE_MS = 1200L;
    static final int DOT_COUNT = 3;
    static final String DISPLAY = "Working...";
    private static final float TAU = (float) (2.0 * Math.PI);

    private WorkingIndicator() {}

    static final String STREAMING = "Streaming…";
    static final String THINKING = "Thinking…";

    /** True only for the exact live lane labels "Streaming…" and "Thinking…". */
    static boolean working(CharSequence stateWords) {
        String s = label(stateWords);
        return STREAMING.equals(s) || THINKING.equals(s);
    }

    static String display(CharSequence stateWords) {
        String state = label(stateWords);
        return STREAMING.equals(state) || THINKING.equals(state) ? DISPLAY : state;
    }

    /** A steady live label lets TalkBack announce the transition without repeating every word. */
    static String line(CharSequence stateWords) {
        return working(stateWords) ? "● " + DISPLAY : "";
    }

    /** The visible count is separate from the live region, so it never repeats a spoken state. */
    static String count(int words) {
        return words <= 0 ? "" : " · " + words + (words == 1 ? " word" : " words");
    }

    /** A spoken label without the moving dot or bar. */
    static String spoken(CharSequence stateWords, int words) {
        String state = label(stateWords);
        state = STREAMING.equals(state) || THINKING.equals(state)
                ? "Working" : state.replace("…", "").trim();
        if (state.isEmpty()) return "";
        int count = Math.max(0, words);
        return count == 0 ? state : state + ", " + count
                + (count == 1 ? " word" : " words");
    }

    private static String label(CharSequence stateWords) {
        return stateWords == null ? "" : stateWords.toString().trim();
    }

    /** One smooth green pulse, with a visible floor so the live dot never disappears. */
    static float dotAlpha(float frame, boolean reducedMotion) {
        return reducedMotion ? 1f : 0.42f + 0.58f * wave(frame);
    }

    /** Three white dots brighten in turn without changing the line's text or width. */
    static float trailingAlpha(float frame, int dot, boolean reducedMotion) {
        if (dot < 0 || dot >= DOT_COUNT) throw new IllegalArgumentException("dot");
        return reducedMotion ? 1f : 0.30f + 0.70f * wave(frame - dot / (float) DOT_COUNT);
    }

    /** A stopped, hidden or reduced-motion card never gets animation frames. */
    static boolean animate(boolean live, boolean onScreen, boolean resumed,
                           boolean reducedMotion, boolean animatorsEnabled) {
        return live && onScreen && resumed && !reducedMotion && animatorsEnabled;
    }

    private static float wave(float frame) {
        return 0.5f + 0.5f * (float) Math.cos(TAU * frame);
    }
}

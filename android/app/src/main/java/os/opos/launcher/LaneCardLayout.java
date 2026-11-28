package os.opos.launcher;

/**
 * Host-testable layout constants for model lane cards. Cards wrap their content
 * and share one typography set (header, subheader, body) from {@link TypeConfig}.
 * Frames stay thin and recessive. Sizes here document the recommended H5+S5+B5
 * default; {@link #bodySp}, {@link #headingSp} and {@link #labelSp} follow the
 * live TypeConfig pick.
 */
final class LaneCardLayout {
    enum Part { KICKER, HEADING, ANSWER }

    /**
     * Walls stay quieter than the words: a hairline in a dark gray, well under the #fff text.
     * #5C5C5C on #000 is about 3.1:1, the minimum contrast for a UI boundary.
     */
    static final float STROKE_DP = 0.5f;
    static final int CARD_PADDING_DP = 8;
    static final int CARD_GAP_DP = 6;
    /** Recommended default (H5+S5+B5), 1.25 modular scale: 11 / 17 / 21. */
    static final int BODY_SP_FULL = 17;
    static final int LABEL_SP = 11;
    /** Minimum height so an empty or waiting lane still reads as a frame. */
    static final int MIN_LANE_DP = 96;
    /** Subtle card height animation while an answer streams, clears, or retries. */
    static final int GROW_MS = 140;

    private LaneCardLayout() {}

    static boolean wrapsToContent() {
        return true;
    }

    /** A queued lane keeps its identity visible before any answer arrives. */
    static boolean waitingVisible(boolean waiting, Part part) {
        return !waiting || part != Part.ANSWER;
    }

    static int bodySp(boolean cover, boolean compact) {
        return TypeConfig.body().size(cover);
    }

    /** Same header size on every lane; slot flags are ignored so cards stay consistent. */
    static int headingSp(boolean extra, boolean gpuLead) {
        return headingSp(false);
    }

    static int headingSp(boolean cover) {
        return TypeConfig.header().size(cover);
    }

    static int labelSp(boolean cover) {
        return TypeConfig.subheader().size(cover);
    }

    static int gapDp(int index) {
        return index == 0 ? 0 : CARD_GAP_DP;
    }
}

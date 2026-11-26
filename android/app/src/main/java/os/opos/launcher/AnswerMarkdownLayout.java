package os.opos.launcher;

/** Pixel margins for answer paragraphs, kept independent of Android for host checks. */
final class AnswerMarkdownLayout {
    static final class Margins {
        final int first;
        final int rest;

        Margins(int first, int rest) {
            this.first = first;
            this.rest = rest;
        }
    }

    private AnswerMarkdownLayout() {}

    static Margins list(float literalIndent, float markerWidth,
                        float hierarchyStepWidth, int depth) {
        float target = Math.max(literalIndent, hierarchyStepWidth * depth);
        return new Margins(Math.round(target - literalIndent),
                Math.round(target + markerWidth));
    }

    static int quote(float twoSpaceWidth) {
        return Math.round(twoSpaceWidth);
    }
}

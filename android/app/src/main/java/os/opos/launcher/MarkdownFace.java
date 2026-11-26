package os.opos.launcher;

/** Which typeface family each Markdown mark uses; code must stay monospaced. */
final class MarkdownFace {
    static final int NONE = 0;
    static final int BOLD = 1;
    static final int ITALIC = 2;
    static final int MONOSPACE = 3;

    private MarkdownFace() {}

    static int forMark(int parserKind) {
        switch (parserKind) {
            case AnswerMarkdownParser.BOLD:
                return BOLD;
            case AnswerMarkdownParser.ITALIC:
                return ITALIC;
            case AnswerMarkdownParser.CODE:
                return MONOSPACE;
            default:
                return NONE;
        }
    }
}

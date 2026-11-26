package os.opos.launcher;

/** Places a notepad rule a small distance below its text baseline. */
final class NotesRulePosition {
    private NotesRulePosition() {}

    static int ruleY(int baseline, int lineBottom, int lineHeight) {
        if (lineHeight <= 0) throw new IllegalArgumentException("lineHeight");
        int descent = Math.max(0, lineBottom - baseline);
        return baseline + Math.min(descent / 2, lineHeight / 8);
    }
}

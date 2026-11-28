package os.opos.launcher;

/** Text shown on answer cards; keep the service's stored answer unchanged. */
final class AnswerDisplay {
    private AnswerDisplay() {}

    static String text(String pane, String source) {
        String value = source == null ? "" : source;
        return PaneKeys.pc(pane) ? value : LeadingWhitespace.strip(value);
    }
}

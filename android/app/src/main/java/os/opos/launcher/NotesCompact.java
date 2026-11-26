package os.opos.launcher;

/** The NOTES card collapses to its content: one short line when empty, grows as you type. */
final class NotesCompact {
    /** Card minimum height. The card used to reserve 160 dp even with nothing in it. */
    static final int CARD_MIN_EMPTY_DP = 0;
    static final int CARD_MIN_FILLED_DP = 0;
    /** One writing line (16 sp at 1.6 leading plus padding) so the empty card stays tappable. */
    static final int EDITOR_MIN_EMPTY_DP = 40;
    static final int EDITOR_MIN_FILLED_DP = 40;
    static final String EMPTY_HINT = "Tap to add a note";

    private NotesCompact() {}

    static boolean empty(CharSequence text) {
        return text == null || text.toString().trim().isEmpty();
    }

    static int cardMinDp(CharSequence text) {
        return empty(text) ? CARD_MIN_EMPTY_DP : CARD_MIN_FILLED_DP;
    }

    static int editorMinDp(CharSequence text) {
        return empty(text) ? EDITOR_MIN_EMPTY_DP : EDITOR_MIN_FILLED_DP;
    }

    /** Ruled filler lines below the text are only drawn when there is text to rule. */
    static boolean drawFillerRules(CharSequence text) {
        return !empty(text);
    }
}

package os.opos.launcher;

/**
 * Host-testable rules for dragging a lane card onto Notes. Formatting and
 * hit-testing live here; Android drag plumbing stays in MainActivity.
 */
final class NotesDrop {
    /** About one second, longer than a tap and the usual 400–500 ms long-press. */
    static final int LONG_PRESS_MS = 1000;
    static final String ACTION_LABEL = "Save to Notes";
    static final String MIME = "text/plain";

    private NotesDrop() {}

    /** Drag-to-Notes is offered whenever the Notes tab is on screen. */
    static boolean available(boolean notesVisible) {
        return notesVisible;
    }

    static boolean isDropOnNotes(int x, int y, int left, int top, int right, int bottom) {
        return x >= left && x < right && y >= top && y < bottom;
    }

    static boolean movedTooFar(float dx, float dy, float slop) {
        return dx * dx + dy * dy > slop * slop;
    }

    /**
     * A readable block: model name, question, answer, timestamp, each on its
     * own section. Empty parts are omitted.
     */
    static String format(String model, String question, String answer, String timestamp) {
        StringBuilder block = new StringBuilder();
        appendSection(block, model);
        appendSection(block, question);
        appendSection(block, answer);
        appendSection(block, timestamp);
        return block.toString();
    }

    static String append(String existing, String addition) {
        String extra = addition == null ? "" : addition.trim();
        if (extra.isEmpty()) return existing == null ? "" : existing;
        String current = existing == null ? "" : existing.replaceAll("\\s+$", "");
        if (current.isEmpty()) return extra;
        return current + "\n\n" + extra;
    }

    private static void appendSection(StringBuilder block, String value) {
        if (value == null) return;
        String trimmed = value.trim();
        if (trimmed.isEmpty()) return;
        if (block.length() > 0) block.append('\n');
        block.append(trimmed);
    }
}

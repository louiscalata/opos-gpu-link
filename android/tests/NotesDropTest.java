package os.opos.launcher;

public final class NotesDropTest {
    public static void main(String[] args) {
        equal(1000, NotesDrop.LONG_PRESS_MS);
        equal("Save to Notes", NotesDrop.ACTION_LABEL);
        check(NotesDrop.available(true));
        check(!NotesDrop.available(false));

        check(NotesDrop.isDropOnNotes(10, 20, 0, 0, 50, 80));
        check(NotesDrop.isDropOnNotes(0, 0, 0, 0, 50, 80));
        check(!NotesDrop.isDropOnNotes(50, 20, 0, 0, 50, 80));
        check(!NotesDrop.isDropOnNotes(10, 80, 0, 0, 50, 80));
        check(!NotesDrop.isDropOnNotes(-1, 20, 0, 0, 50, 80));

        check(!NotesDrop.movedTooFar(3, 4, 5));
        check(NotesDrop.movedTooFar(3, 4, 4.9f));

        equal("Qwen2.5 1.5B\nWhy do GPUs help with AI?\nA graphics processor.\nWednesday, November 25, 2026, 6:40 PM",
                NotesDrop.format("Qwen2.5 1.5B", "Why do GPUs help with AI?",
                        "A graphics processor.", "Wednesday, November 25, 2026, 6:40 PM"));
        equal("Phone\nJust the model", NotesDrop.format("Phone", "", "  ", "Just the model"));
        equal("Only answer", NotesDrop.format("  ", null, "Only answer", ""));
        equal("", NotesDrop.format(null, null, null, null));

        equal("First note\n\nSecond note", NotesDrop.append("First note", "Second note"));
        equal("First note\n\nSecond note", NotesDrop.append("First note\n\n", "Second note"));
        equal("Only", NotesDrop.append("", "Only"));
        equal("Only", NotesDrop.append(null, "Only"));
        equal("Keep", NotesDrop.append("Keep", "  "));
        equal("", NotesDrop.append(null, null));
        // The bottom folder tab uses the same hit-testing when it is the drop target.
        check(NotesDrop.isDropOnNotes(20, 10, 0, 0, 200, 36));
        check(!NotesDrop.isDropOnNotes(20, 40, 0, 0, 200, 36));
        check(NotesSheet.available(true));
        check(NotesDrop.available(NotesSheet.available(false)));
        check(NotesDrop.available(NotesSheet.available(true)));
        System.out.println("NotesDropTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected " + expected + ", got " + actual);
        }
    }
}

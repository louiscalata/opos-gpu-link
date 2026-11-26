package os.opos.launcher;

import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** The masthead's four-action menu state, independent of Android views. */
final class MenuState {
    static final List<String> ENTRIES = Collections.unmodifiableList(Arrays.asList(
            "Model Selection", "History", "Settings", "Quit"));
    private boolean open;

    boolean isOpen() { return open; }
    void toggle() { open = !open; }
    void dismiss() { open = false; }

    String select(int index) {
        if (!open || index < 0 || index >= ENTRIES.size()) return null;
        open = false;
        return ENTRIES.get(index);
    }
}

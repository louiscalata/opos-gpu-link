package os.opos.launcher;

import java.util.Arrays;

public final class MenuStateTest {
    public static void main(String[] args) {
        MenuState state = new MenuState();
        equal(Arrays.asList("Model Selection", "History", "Settings", "Quit"),
                MenuState.ENTRIES);
        check(!state.isOpen());
        state.toggle();
        check(state.isOpen());
        equal("History", state.select(1));
        check(!state.isOpen());
        equal(null, state.select(0));
        state.toggle();
        state.dismiss();
        check(!state.isOpen());
        state.toggle();
        state.toggle();
        check(!state.isOpen());
        System.out.println("MenuStateTest: OK");
    }
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) throw new AssertionError();
    }
}

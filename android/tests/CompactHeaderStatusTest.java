package os.opos.launcher;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

public final class CompactHeaderStatusTest {
    public static void main(String[] args) {
        String paused = "Paused — will continue when the PC is back";
        equal("This phone: Working... · PC GPU: Paused",
                CompactHeaderStatus.line("This phone", "Streaming…", "PC GPU",
                        paused, paused));
        equal("This phone: Working... · PC GPU: Working...",
                CompactHeaderStatus.line("This phone", "Thinking…", "PC GPU",
                        "Streaming…", paused));
        equal("This phone: Ready · PC GPU: Waiting for the PC",
                CompactHeaderStatus.line("This phone", "Ready", "PC GPU",
                        "Waiting for the PC", paused));
        Map<String, String> states = new HashMap<>();
        states.put("m1", "Streaming…");
        states.put("g1", paused);
        equal("Streaming…", CompactHeaderStatus.selectedState(
                Arrays.asList("g1", "m1"), states, false, "Not asked this time", "Checking…"));
        equal(paused, CompactHeaderStatus.selectedState(
                Arrays.asList("g1", "m1"), states, true, "Not asked this time", "Checking…"));
        equal("Not asked this time", CompactHeaderStatus.selectedState(
                Arrays.asList("g1"), states, false, "Not asked this time", "Checking…"));
        equal("Checking…", CompactHeaderStatus.selectedState(
                Arrays.asList("gpu"), states, true, "Not asked this time", "Checking…"));
        System.out.println("CompactHeaderStatusTest: OK");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

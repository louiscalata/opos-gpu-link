package os.opos.launcher;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

public final class AnswerStartsTest {
    public static void main(String[] args) {
        Map<String, Long> saved = new HashMap<>();
        saved.put("lfm2", 221_000_000L);
        saved.put("future", 999_000_000L);   // from before a reboot: larger than now
        saved.put("zero", 0L);
        saved.put("", 5L);
        Map<String, Long> kept = AnswerStarts.sameBoot(saved, 221_400_000L);
        check(kept.size() == 1);
        check(kept.get("lfm2") == 221_000_000L);

        Map<String, Long> starts = new HashMap<>();
        starts.put("current", 10L);
        starts.put("old", 5L);
        Map<String, Long> toSave = AnswerStarts.toSave(starts, Arrays.asList("current", "other"));
        check(toSave.size() == 1 && toSave.get("current") == 10L);
        System.out.println("AnswerStartsTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError("check failed");
    }
}

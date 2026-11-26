package os.opos.launcher;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.Map;

public final class AnswerStartsTest {
    public static void main(String[] args) {
        // Keys are answer ids, as MainActivity stores them (answerStarts.put(id, ...)).
        Map<String, Long> saved = new HashMap<>();
        saved.put("db2574b20167", 221_000_000L);
        saved.put("e2cc8ab2199e", 221_400_000L);  // equal to now: kept
        saved.put("future", 999_000_000L);        // larger than now: dropped
        saved.put("zero", 0L);
        saved.put("negative", -5L);
        saved.put("nullvalue", null);
        saved.put("", 5L);
        Map<String, Long> kept = AnswerStarts.sameBoot(saved, 41, 41, 221_400_000L);
        check(kept.size() == 2);
        check(kept.get("db2574b20167") == 221_000_000L);
        check(kept.get("e2cc8ab2199e") == 221_400_000L);
        // After a reboot a stale stamp can be smaller than the new uptime: the boot count drops it.
        check(AnswerStarts.sameBoot(saved, 41, 42, 900_000_000L).isEmpty());
        check(AnswerStarts.sameBoot(saved, 41, 41, 900_000_000L).size() == 2); // same-boot control
        check(AnswerStarts.sameBoot(saved, -1, -1, 221_400_000L).isEmpty());
        check(AnswerStarts.sameBoot(null, 41, 41, 1L).isEmpty());

        Map<String, Long> starts = new HashMap<>();
        starts.put("db2574b20167", 10L);
        starts.put("95edbcfb2f5f", 5L);
        Map<String, Long> followed = AnswerStarts.onlyFollowed(starts, Arrays.asList("db2574b20167", "other"));
        check(followed.size() == 1 && followed.get("db2574b20167") == 10L);
        check(AnswerStarts.onlyFollowed(starts, Collections.<String>emptyList()).isEmpty());
        check(AnswerStarts.onlyFollowed(starts, null).isEmpty());
        System.out.println("AnswerStartsTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError("check failed");
    }
}

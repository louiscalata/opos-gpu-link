package os.opos.launcher;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;
import java.util.List;

public final class BackIssueTest {
    public static void main(String[] args) throws Exception {
        HistoryStore.Issue saved = new HistoryStore.Issue("123", 123,
                "Why?", "PC 2.0 s · Phone 1.0 s", "2.1 s", Arrays.asList(
                new HistoryStore.Lane("gpu", "PC GPU", "Maker", "over USB",
                        "Done · 2.0 s", "GPU answer", 2000),
                new HistoryStore.Lane("phone", "This phone", "NVIDIA", "on this phone",
                        "Done · 1.0 s", "Phone answer", 1000)));
        BackIssue issue = BackIssue.from(saved);
        equal("You asked: Why?", issue.headline);
        equal("PC 2.0 s · Phone 1.0 s", issue.timing);
        equal("2.1 s", issue.elapsed);
        equal("", issue.elapsedLabel);
        equal("PC GPU, This phone", issue.answeredBy);
        equal("GPU answer", issue.lanes.get(0).text);
        equal("Phone answer", issue.lanes.get(1).text);
        HistoryStore.Issue paused = new HistoryStore.Issue("124", 124, "Pause?",
                "PC  unmeasured\nPhone  1.0 s", "9.2 s", Arrays.asList(
                new HistoryStore.Lane("gpu", "PC GPU", "Maker", "over USB",
                        "Done · time unmeasured", "partial finished", -1),
                new HistoryStore.Lane("phone", "This phone", "Maker", "on this phone",
                        "Done · 1.0 s", "Phone answer", 1000)), true);
        Map<String, String> values = new HashMap<>();
        HistoryStore store = new HistoryStore(new HistoryStore.Store() {
            public String get(String key) { return values.get(key); }
            public void update(Map<String, String> writes, List<String> removals) {
                for (String key : removals) values.remove(key);
                values.putAll(writes);
            }
        });
        store.upsert(paused);
        BackIssue resumed = BackIssue.from(store.list().get(0));
        equal("PC  unmeasured\nPhone  1.0 s", resumed.timing);
        equal("9.2 s", resumed.elapsed);
        equal("Wall elapsed · includes pause", resumed.elapsedLabel);
        equal("Done · time unmeasured", resumed.lanes.get(0).state);
        equal(-1L, resumed.lanes.get(0).elapsedMs);

        values.clear();
        values.put("history_index_v1", "123");
        values.put("history_issue_v1_123", HistoryStoreTest.legacyPayload());
        List<HistoryStore.Issue> oldEntries = store.list();
        equal(1, oldEntries.size());
        BackIssue old = BackIssue.from(oldEntries.get(0));
        equal("Wall elapsed · pause history unknown", old.elapsedLabel);
        equal("Lane wall elapsed · pause history unknown\nPC  2.0 s\nPhone  1.0 s",
                old.timing);
        equal("Done · 2.0 s wall elapsed (pause history unknown)",
                old.lanes.get(0).state);
        equal("Done · 1.0 s wall elapsed (pause history unknown)",
                old.lanes.get(1).state);
        System.out.println("BackIssueTest: OK");
    }
    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

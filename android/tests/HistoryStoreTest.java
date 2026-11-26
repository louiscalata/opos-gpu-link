package os.opos.launcher;

import java.io.ByteArrayOutputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class HistoryStoreTest {
    public static void main(String[] args) throws IOException {
        Map<String, String> values = new HashMap<>();
        HistoryStore.Store memory = new HistoryStore.Store() {
            public String get(String key) { return values.get(key); }
            public void update(Map<String, String> writes, List<String> removals) {
                for (String key : removals) values.remove(key);
                values.putAll(writes);
            }
        };
        HistoryStore history = new HistoryStore(memory);
        HistoryStore.Issue first = issue(1, "first", "hello **world**");
        history.upsert(first);
        HistoryStore.Issue roundTrip = new HistoryStore(memory).list().get(0);
        equal(first.question, roundTrip.question);
        equal(first.timing, roundTrip.timing);
        equal(first.elapsed, roundTrip.elapsed);
        equal(first.lanes.get(0).text, roundTrip.lanes.get(0).text);
        equal(first.lanes.get(0).elapsedMs, roundTrip.lanes.get(0).elapsedMs);
        check(roundTrip.pauseProvenanceKnown);
        check(!roundTrip.pauseObserved);
        for (int i = 2; i <= 55; i++) history.upsert(issue(i, "question " + i, "answer " + i));
        List<HistoryStore.Issue> capped = new HistoryStore(memory).list();
        equal(50, capped.size());
        equal("55", capped.get(0).id);
        equal("6", capped.get(49).id);
        history.upsert(issue(55, "revised", "saved"));
        equal(50, history.list().size());
        equal("revised", history.list().get(0).question);
        history.upsert(issue(56, "long", "x".repeat(300000)));
        String encoded = values.get("history_issue_v1_56");
        check(encoded.length() <= HistoryStore.MAX_ISSUE_BYTES);
        check(Base64.getDecoder().decode(encoded).length <= HistoryStore.MAX_ISSUE_BYTES);
        check(history.list().get(0).lanes.get(0).text.length() < 300000);
        check(history.list().get(0).lanes.get(0).truncated);
        List<HistoryStore.Lane> oversizedMetadata = new ArrayList<>();
        oversizedMetadata.add(new HistoryStore.Lane("g1", "L".repeat(300000),
                "M".repeat(300000), "W".repeat(300000), "Done", "answer", 5));
        history.upsert(new HistoryStore.Issue("57", 57, "metadata", "5 ms", "5 ms",
                oversizedMetadata));
        check(values.get("history_issue_v1_57").length() <= HistoryStore.MAX_ISSUE_BYTES);
        check(history.list().get(0).lanes.get(0).label.length() < 300000);
        history.clear("57");
        equal("57", values.get(HistoryStore.SUPPRESSED));
        equal(0, history.list().size());
        history.upsert(issue(58, "after clear", "new answer"));
        equal("58", history.list().get(0).id);
        history.clear();
        equal(0, new HistoryStore(memory).list().size());
        check(values.keySet().stream().noneMatch(key -> key.startsWith("history_")));
        HistoryStore.Issue paused = new HistoryStore.Issue("99", 99, "paused?",
                "PC  unmeasured\nPhone  1.0 s", "9.2 s", List.of(
                new HistoryStore.Lane("gpu", "PC GPU", "Maker", "over USB",
                        "Done · time unmeasured", "partial finished", -1),
                new HistoryStore.Lane("phone", "This phone", "Maker", "on this phone",
                        "Done · 1.0 s", "phone answer", 1000)), true);
        history.upsert(paused);
        HistoryStore.Issue savedPause = history.list().get(0);
        check(savedPause.pauseProvenanceKnown);
        check(savedPause.pauseObserved);
        equal(-1, savedPause.lanes.get(0).elapsedMs);
        equal("PC  unmeasured\nPhone  1.0 s", savedPause.timing);
        equal("Done · time unmeasured", savedPause.lanes.get(0).state);
        history.clear();
        values.put("history_index_v1", "123");
        values.put("history_issue_v1_123", legacyPayload());
        HistoryStore.Issue legacy = history.list().get(0);
        check(!legacy.pauseProvenanceKnown);
        check(!legacy.pauseObserved);
        equal(2000, legacy.lanes.get(0).elapsedMs);
        equal("Done · 2.0 s", legacy.lanes.get(0).state);
        history.upsert(legacy);
        check(!history.list().get(0).pauseProvenanceKnown);
        equal("", history.list().get(0).sourceId);
        history.clear();
        values.put("history_index_v1", "99");
        values.put("history_issue_v1_99", pauseVersionPayload());
        HistoryStore.Issue pauseVersion = history.list().get(0);
        check(pauseVersion.pauseProvenanceKnown);
        check(pauseVersion.pauseObserved);
        equal("", pauseVersion.sourceId);
        equal("Why?", pauseVersion.question);
        history.clear();
        HistoryStore.Issue root = issue(10, "Why do GPUs help with AI?", "first answer");
        history.upsert(root);
        HistoryStore.Issue linked = new HistoryStore.Issue("11", 11, root.question,
                root.timing, root.elapsed, root.lanes, false, root.id);
        history.upsert(linked);
        HistoryStore.Issue savedRoot = null;
        HistoryStore.Issue savedLink = null;
        for (HistoryStore.Issue item : history.list()) {
            if ("10".equals(item.id)) savedRoot = item;
            if ("11".equals(item.id)) savedLink = item;
        }
        equal(root.question, savedRoot.question);
        equal("first answer", savedRoot.lanes.get(0).text);
        equal("10", savedLink.sourceId);
        equal("", savedRoot.sourceId);
        equal(2, history.list().size());
        System.out.println("HistoryStoreTest: OK");
    }

    static String pauseVersionPayload() throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        DataOutputStream out = new DataOutputStream(bytes);
        out.writeInt(2);
        legacyString(out, "99");
        out.writeLong(99);
        legacyString(out, "Why?");
        legacyString(out, "PC  unmeasured");
        legacyString(out, "unmeasured");
        out.writeBoolean(true);
        out.writeBoolean(true);
        out.writeInt(1);
        legacyLane(out, "gpu", "PC GPU", "over USB", "Done · time unmeasured",
                "GPU answer", -1);
        out.flush();
        return Base64.getEncoder().encodeToString(bytes.toByteArray());
    }

    static String legacyPayload() throws IOException {
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        DataOutputStream out = new DataOutputStream(bytes);
        out.writeInt(1);
        legacyString(out, "123");
        out.writeLong(123);
        legacyString(out, "Why?");
        legacyString(out, "PC  2.0 s\nPhone  1.0 s");
        legacyString(out, "2.1 s");
        out.writeInt(2);
        legacyLane(out, "gpu", "PC GPU", "over USB", "Done · 2.0 s",
                "GPU answer", 2000);
        legacyLane(out, "phone", "This phone", "on this phone", "Done · 1.0 s",
                "Phone answer", 1000);
        out.flush();
        return Base64.getEncoder().encodeToString(bytes.toByteArray());
    }

    private static void legacyLane(DataOutputStream out, String pane, String label,
                                   String where, String state, String answer, long elapsed)
            throws IOException {
        legacyString(out, pane);
        legacyString(out, label);
        legacyString(out, "Maker");
        legacyString(out, where);
        legacyString(out, state);
        legacyString(out, answer);
        out.writeLong(elapsed);
        out.writeBoolean(false);
    }

    private static void legacyString(DataOutputStream out, String value) throws IOException {
        byte[] encoded = value.getBytes(StandardCharsets.UTF_8);
        out.writeInt(encoded.length);
        out.write(encoded);
    }

    private static HistoryStore.Issue issue(long id, String question, String answer) {
        List<HistoryStore.Lane> lanes = new ArrayList<>();
        lanes.add(new HistoryStore.Lane("phone", "This phone", "NVIDIA", "on this phone",
                "Done · 1.2 s", answer, 1200));
        return new HistoryStore.Issue(Long.toString(id), id, question,
                "Phone 1.2 s", "1.2 s", lanes);
    }

    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
    private static void equal(long expected, long actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

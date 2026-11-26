package os.opos.launcher;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class HistoryRefreshTest {
    public static void main(String[] args) {
        HistoryStore.Lane phoneThen = new HistoryStore.Lane("phone", "This phone", "Qwen",
                "on this phone", "Done · 1.2 s", "Then phone answer", 1200);
        HistoryStore.Lane gpuThen = new HistoryStore.Lane("gpu", "PC GPU", "Maker",
                "over USB", "Failed", "Then GPU failed", 800);
        HistoryStore.Issue original = new HistoryStore.Issue("100", 100,
                "Why do GPUs help with AI?", "Phone 1.2 s\nPC 0.8 s", "1.2 s",
                Arrays.asList(phoneThen, gpuThen));
        HistoryStore.Lane phoneNow = new HistoryStore.Lane("phone", "This phone", "Qwen",
                "on this phone", "Done · 1.0 s", "Now phone answer", 1000);
        HistoryStore.Lane extraNow = new HistoryStore.Lane("m1", "MacBook", "Maker",
                "on the MacBook", "Stuck — Retry", "Now stuck", 5000);
        HistoryStore.Issue refresh = new HistoryStore.Issue("200", 200,
                "Why do GPUs help with AI?", "Phone 1.0 s", "1.0 s",
                Arrays.asList(phoneNow, extraNow), false, "100");

        List<HistoryStore.Issue> issues = Arrays.asList(refresh, original);
        equal("100", HistoryRefresh.open(issues, "100").id);
        equal("200", HistoryRefresh.open(issues, "200").id);
        check(HistoryRefresh.open(issues, "999") == null);
        check(HistoryRefresh.open(issues, "") == null);
        check(HistoryRefresh.open(null, "100") == null);

        equal("Why do GPUs help with AI?", HistoryRefresh.payload(original));
        equal("Why do GPUs help with AI?", HistoryRefresh.payload(refresh));
        check(HistoryRefresh.canRefresh(original));
        HistoryStore.Issue bare = new HistoryStore.Issue("300", 300, "again",
                "", "", Arrays.asList(phoneThen));
        equal("", HistoryRefresh.payload(bare));
        check(!HistoryRefresh.canRefresh(bare));
        HistoryStore.Issue retryWord = new HistoryStore.Issue("301", 301, "  Try again.  ",
                "", "", Arrays.asList(phoneThen));
        equal("", HistoryRefresh.payload(retryWord));

        equal("100", HistoryRefresh.rootId(original));
        equal("100", HistoryRefresh.rootId(refresh));
        check(HistoryRefresh.linked(original, refresh));
        check(!HistoryRefresh.linked(original, original));
        check(!HistoryRefresh.linked(original, bare));
        check(HistoryRefresh.originalPreserved(original, original));
        equal("100", HistoryRefresh.originalOf(issues, refresh).id);
        equal("200", HistoryRefresh.latestRefresh(issues, original).id);

        List<HistoryRefresh.LaneCompare> rows = HistoryRefresh.compare(original, refresh);
        equal(3, rows.size());
        equal("phone", rows.get(0).pane);
        check(rows.get(0).presentThen && rows.get(0).presentNow);
        equal(UiPalette.Tone.OK, rows.get(0).thenTone);
        equal(UiPalette.Tone.OK, rows.get(0).nowTone);
        equal("Now phone answer", rows.get(0).nowText);
        equal("gpu", rows.get(1).pane);
        check(rows.get(1).presentThen && !rows.get(1).presentNow);
        equal(UiPalette.Tone.ERROR, rows.get(1).thenTone);
        equal("m1", rows.get(2).pane);
        check(!rows.get(2).presentThen && rows.get(2).presentNow);
        equal(UiPalette.Tone.ERROR, rows.get(2).nowTone);

        Map<String, String> values = new HashMap<>();
        HistoryStore store = new HistoryStore(new HistoryStore.Store() {
            public String get(String key) { return values.get(key); }
            public void update(Map<String, String> writes, List<String> removals) {
                for (String key : removals) values.remove(key);
                values.putAll(writes);
            }
        });
        store.upsert(original);
        String beforeQuestion = store.list().get(0).question;
        store.upsert(refresh);
        List<HistoryStore.Issue> saved = store.list();
        equal(2, saved.size());
        HistoryStore.Issue savedOriginal = HistoryRefresh.open(saved, "100");
        HistoryStore.Issue savedRefresh = HistoryRefresh.open(saved, "200");
        equal(beforeQuestion, savedOriginal.question);
        check(HistoryRefresh.originalPreserved(original, savedOriginal));
        check(HistoryRefresh.linked(savedOriginal, savedRefresh));
        equal("100", savedRefresh.sourceId);
        equal("Why do GPUs help with AI?", HistoryRefresh.payload(savedRefresh));
        System.out.println("HistoryRefreshTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected " + expected + ", got " + actual);
        }
    }
    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

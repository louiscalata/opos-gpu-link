package os.opos.launcher;

import java.util.Arrays;
import java.util.List;

public final class NewspaperSummaryTest {
    public static void main(String[] args) {
        equal(0, NewspaperSummary.wordCount("  -  •  "));
        equal(3, NewspaperSummary.wordCount("First **bold** word"));
        equal(2, NewspaperSummary.wordCount("Hello,\nworld!"));
        equal("4.8 s", NewspaperSummary.seconds(4800));
        equal("PC 4.8 s · Phone 1.6 s", NewspaperSummary.timing(4800L, 1600L));
        equal("PC … · Phone 1.6 s", NewspaperSummary.timing(null, 1600L));
        equal("PC · 2 words · Streaming…",
                NewspaperSummary.line("PC", "hello world", "Streaming…"));
        equal("Phone · 1 word · Done · 1.6 s",
                NewspaperSummary.line("Phone", "hello", "Done · 1.6 s"));
        equal("Phone finished first by 3.2 s",
                NewspaperSummary.finishedFirst("Done · 4.8 s", 4800L,
                        "Done · 1.6 s", 1600L));
        equal("PC finished first by 3.2 s",
                NewspaperSummary.finishedFirst("Done · 1.6 s", 1600L,
                        "Done · 4.8 s", 4800L));
        equal("", NewspaperSummary.finishedFirst("Streaming…", null,
                "Done · 1.6 s", 1600L));
        equal("Finish order unavailable", NewspaperSummary.finishedFirst("Done", null,
                "Done · 1.6 s", 1600L));
        List<NewspaperSummary.Lane> lanes = Arrays.asList(
                new NewspaperSummary.Lane("PC", "one two three", "Done · 4.8 s", 4800L),
                new NewspaperSummary.Lane("Phone", "one", "Done · 1.6 s", 1600L),
                new NewspaperSummary.Lane("Qwen", "one two", "Done · 7.0 s", 7000L));
        equal("PC\u00a04.8\u00a0s\nPhone\u00a01.6\u00a0s\nQwen\u00a07.0\u00a0s",
                NewspaperSummary.timing(lanes));
        equal("PC\u00a0waiting\nQwen2.5 1.5B\u00a0—\nGranite\u00a07.0\u00a0s",
                NewspaperSummary.timing(Arrays.asList(
                        new NewspaperSummary.Lane("PC", "partial", "Paused", null,
                                null, true, 1, true),
                        new NewspaperSummary.Lane("Qwen2.5 1.5B", "", "Not asked this time",
                                null, false),
                        new NewspaperSummary.Lane("Granite", "answer", "Done", 7000L))));
        String report = NewspaperSummary.report(lanes);
        contains(report, "PC · 3 words · Done · 4.8 s");
        contains(report, "Fastest: Phone (1.6 s) · Slowest: Qwen (7.0 s)");
        contains(report, "Longest answer: PC (3 words)");
        contains(report, "Phone finished first by 3.2 s");
        String partial = NewspaperSummary.report(Arrays.asList(
                lanes.get(0), new NewspaperSummary.Lane("Phone", "one", "Streaming…", null)));
        contains(partial, "Fastest so far: PC");
        check(!partial.contains("finished first by"));
        String othersWaiting = NewspaperSummary.report(Arrays.asList(
                lanes.get(0), lanes.get(1),
                new NewspaperSummary.Lane("Qwen", "", "Waiting for its turn…", null)));
        contains(othersWaiting, "Phone finished first by 3.2 s");
        String retried = NewspaperSummary.report(Arrays.asList(
                new NewspaperSummary.Lane("PC", "old", "Done · 4.8 s",
                        4800L, 5000L, true),
                new NewspaperSummary.Lane("Phone", "new", "Done · 1.0 s",
                        1000L, 12000L, true),
                new NewspaperSummary.Lane("Qwen", "later", "Done · 2.0 s",
                        2000L, 15000L, true)));
        contains(retried, "PC finished first by 7.0 s");
        contains(retried, "Fastest: Phone (1.0 s)");
        String unasked = NewspaperSummary.report(Arrays.asList(
                new NewspaperSummary.Lane("PC", "one two", "Done · 2.0 s", 2000L),
                new NewspaperSummary.Lane("Phone", "", "Not asked this time", null, false),
                new NewspaperSummary.Lane("Qwen", "", "Ready", null, false)));
        contains(unasked, "Fastest: PC (2.0 s)");
        check(!unasked.contains("Slowest"));
        check(!unasked.contains("finished first by"));
        NewspaperSummary.Lane pausedPc = new NewspaperSummary.Lane("PC", "partial",
                "Paused — will continue when the PC is back", null, null,
                true, 1, true, "paused");
        NewspaperSummary.Lane phoneDuringPause = new NewspaperSummary.Lane("Phone", "answer",
                "Done · 1.0 s", 1000L, 1500L, true);
        equal("PC\u00a0paused\nPhone\u00a01.0\u00a0s", NewspaperSummary.timing(
                Arrays.asList(pausedPc, phoneDuringPause)));
        String duringPause = NewspaperSummary.report(
                Arrays.asList(pausedPc, phoneDuringPause));
        contains(duringPause, "Fastest so far: Phone (1.0 s)");
        check(!duringPause.contains("finished first by"));
        NewspaperSummary.Lane resumedPc = new NewspaperSummary.Lane("PC", "partial finished",
                "Done · time unmeasured", null, null, true, 2, false, "unmeasured");
        equal("PC\u00a0unmeasured\nPhone\u00a01.0\u00a0s", NewspaperSummary.timing(
                Arrays.asList(resumedPc, phoneDuringPause)));
        equal("Long lane label\u00a03.3\u00a0s",
                NewspaperSummary.timingRow("Long lane label", "3.3 s"));
        equal("Lane wall elapsed · pause history unknown\nPC\u00a02.0\u00a0s",
                NewspaperSummary.timingForDisplay(
                        "Lane wall elapsed · pause history unknown\nPC  2.0 s"));
        String afterResume = NewspaperSummary.report(
                Arrays.asList(resumedPc, phoneDuringPause));
        contains(afterResume, "Fastest: Phone (1.0 s)");
        check(!afterResume.contains("Slowest"));
        contains(afterResume, "Finish order unavailable");
        check(!afterResume.contains("Fastest: PC"));
        check(!afterResume.contains("Slowest: PC"));
        check(!afterResume.contains("finished first by"));
        // While the PC is paused only the phone has a time; it must not be both ends.
        check(!duringPause.contains("Slowest"));
        NewspaperSummary.Lane tieA = new NewspaperSummary.Lane("PC", "a b",
                "Done · 2.00 s", 2000L, 2000L, true);
        NewspaperSummary.Lane tieB = new NewspaperSummary.Lane("Phone", "a b",
                "Done · 2.02 s", 2020L, 2020L, true);
        String tie = NewspaperSummary.report(Arrays.asList(tieA, tieB));
        contains(tie, "PC and Phone finished together");
        check(!tie.contains("finished first by 0.0 s"));
        contains(tie, "Fastest: PC (2.0 s) · Slowest: Phone (2.0 s)");
        String exact = NewspaperSummary.report(Arrays.asList(
                new NewspaperSummary.Lane("PC", "a", "Done · 2.0 s", 2000L, 2000L, true),
                new NewspaperSummary.Lane("Phone", "b", "Done · 2.0 s", 2000L, 2000L, true)));
        contains(exact, "Fastest: PC (2.0 s) · Slowest: Phone (2.0 s)");
        // The finish margin is wall time; after a cable pull it must say so, because the
        // lane's own Done time has the pause taken out (live: PC 11.1 s, Phone 87.1 s,
        // "PC finished first by 49.9 s").
        NewspaperSummary.Lane pausedPcDone = new NewspaperSummary.Lane("PC", "a b c",
                "Done · 11.1 s", 11100L, 37200L, true, 3, false, null, true);
        NewspaperSummary.Lane phoneDone = new NewspaperSummary.Lane("Phone", "a b",
                "Done · 87.1 s", 87100L, 87100L, true, 2, false, null, false);
        String pausedReport = NewspaperSummary.report(Arrays.asList(pausedPcDone, phoneDone));
        contains(pausedReport, "Fastest: PC (11.1 s)");
        contains(pausedReport, "PC finished first by 49.9 s · includes pause");
        NewspaperSummary.Lane cleanPcDone = new NewspaperSummary.Lane("PC", "a b c",
                "Done · 11.1 s", 11100L, 11100L, true, 3, false, null);
        String cleanReport = NewspaperSummary.report(Arrays.asList(cleanPcDone, phoneDone));
        contains(cleanReport, "PC finished first by 76.0 s");
        check(!cleanReport.contains("includes pause"));
        // TONIGHT total after an app restart: last finish stamp minus the question start.
        long start = 221_000_000L;
        equal(305400L, NewspaperSummary.totalFromFinishes(Arrays.asList(
                new NewspaperSummary.Lane("PC", "a", "Done · 7.0 s", 7000L, start + 7000L, true),
                new NewspaperSummary.Lane("Granite", "b", "Done · 305.4 s", 305400L, start + 305400L, true),
                new NewspaperSummary.Lane("Qwen", "", "Not asked this time", null, false)), start));
        check(NewspaperSummary.totalFromFinishes(Arrays.asList(
                new NewspaperSummary.Lane("PC", "a", "Done", null, null, true)), start) == null);
        check(NewspaperSummary.totalFromFinishes(Arrays.asList(
                new NewspaperSummary.Lane("PC", "a", "Done", 7000L, 7000L, true)), 0) == null);
        System.out.println("NewspaperSummaryTest: OK");
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }

    private static void contains(String text, String expected) {
        if (!text.contains(expected)) throw new AssertionError("Missing " + expected + " in " + text);
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
}

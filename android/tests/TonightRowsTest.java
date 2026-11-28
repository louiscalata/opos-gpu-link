package os.opos.launcher;

import java.util.Arrays;
import java.util.List;

public final class TonightRowsTest {
    public static void main(String[] args) {
        List<TonightRows.Row> rows = TonightRows.parse(NewspaperSummary.timing(Arrays.asList(
                new NewspaperSummary.Lane("PC", "a", "Done · 3.3 s", 3300L),
                new NewspaperSummary.Lane("MacBook gemma", "b", "Done · 12.0 s", 12000L),
                new NewspaperSummary.Lane("Phone", "", "Thinking…", null))));
        equal(3, rows.size());
        row(rows.get(0), "PC", "3.3\u00a0s");
        row(rows.get(1), "MacBook gemma", "12.0\u00a0s");
        row(rows.get(2), "Phone", "working");
        // Every row has a label and a value, so the two columns line up.
        for (TonightRows.Row row : rows) check(!row.note());
        List<TonightRows.Row> markers = TonightRows.parse("PC\u00a0paused\nPhone\u00a01.0\u00a0s");
        row(markers.get(0), "PC", "paused");
        row(markers.get(1), "Phone", "1.0\u00a0s");
        // A line that is a note (no value) spans the card.
        List<TonightRows.Row> note = TonightRows.parse(
                "Lane wall elapsed · pause history unknown\nPC\u00a02.0\u00a0s");
        check(note.get(0).note());
        equal("Lane wall elapsed · pause history unknown", note.get(0).label);
        row(note.get(1), "PC", "2.0\u00a0s");
        // Older saved issues used two spaces between label and value.
        row(TonightRows.parse("PC  2.0 s").get(0), "PC", "2.0\u00a0s");
        NewspaperSummary.Lane first = new NewspaperSummary.Lane(
                "Nemotron Mini 4B", "one", "Done", 1000L);
        NewspaperSummary.Lane second = new NewspaperSummary.Lane(
                "Nemotron Mini 4B", "two words", "Could not finish", null);
        List<NewspaperSummary.Lane> sameNames = Arrays.asList(first, second);
        String duplicateTiming = NewspaperSummary.timing(sameNames);
        List<NewspaperSummary.Lane> matches = TonightRows.matchingLanes(
                TonightRows.parse(duplicateTiming), sameNames);
        check(matches.get(0) == first);
        check(matches.get(1) == second);
        List<NewspaperSummary.Lane> withNote = TonightRows.matchingLanes(
                TonightRows.parse("A note\n" + duplicateTiming), sameNames);
        check(withNote.get(0) == null);
        check(withNote.get(1) == first);
        check(withNote.get(2) == second);
        NewspaperSummary.Lane stopped = new NewspaperSummary.Lane(
                "Nemotron Mini 4B", "one", "Stopped", 1200L);
        TonightRows.Row stoppedRow = TonightRows.parse(
                NewspaperSummary.timing(Arrays.asList(stopped))).get(0);
        equal(UiPalette.Tone.NEUTRAL, TonightRows.tone(stoppedRow, stopped));
        NewspaperSummary.Lane failed = new NewspaperSummary.Lane(
                "Nemotron Mini 4B", "one", "Stopped early. Here is what it wrote.", 1200L);
        TonightRows.Row failedRow = TonightRows.parse(
                NewspaperSummary.timing(Arrays.asList(failed))).get(0);
        equal(UiPalette.Tone.ERROR, TonightRows.tone(failedRow, failed));
        equal(0, TonightRows.parse("").size());
        equal(0, TonightRows.parse(null).size());
        System.out.println("TonightRowsTest: OK");
    }

    private static void row(TonightRows.Row row, String label, String value) {
        equal(label, row.label);
        equal(value, row.value);
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

package os.opos.launcher;

import java.util.List;

public final class RaceLineTest {
    public static void main(String[] args) {
        NewspaperSummary.Lane macBook = new NewspaperSummary.Lane(
                "MacBook", "ans", "Done", 28400L
        );
        NewspaperSummary.Lane phoneStreaming = new NewspaperSummary.Lane(
                "Phone", "ans", "Streaming…", null
        );
        equal("Fastest so far: MacBook · 28.4 s",
                RaceLine.leader(List.of(macBook, phoneStreaming)));

        equal("■■────── 361 words".replace("■■──────", RaceLine.bar(361, 532, 8)),
                RaceLine.barWithWords(361, 532, 8));
        check(RaceLine.barWithWords(532, 532, 4).equals("■■■■ 532 words"), "longest lane fills");
        check(RaceLine.barWithWords(1, 532, 4).endsWith(" 1 word"), "singular word");
        equal("", RaceLine.barWithWords(5, 10, 0));
        equal("MacBook, 9.0 s, 361 words", RaceLine.rowDescription("MacBook", "9.0\u00a0s", 361));
        equal("Phone, 0 words", RaceLine.rowDescription("Phone", "", 0));

        NewspaperSummary.Lane phoneDone = new NewspaperSummary.Lane(
                "Phone", "ans", "Done", 108100L
        );
        check("Fastest: MacBook · 28.4 s".equals(
                RaceLine.leader(List.of(macBook, phoneDone))
        ), "leader with both done should be fastest");

        NewspaperSummary.Lane ignoredFast = new NewspaperSummary.Lane(
                "Ignored", "ans", "Done", 1000L, null, false, 0, false, null, false
        );
        check("Fastest: MacBook · 28.4 s".equals(
                RaceLine.leader(List.of(ignoredFast, macBook))
        ), "leader should ignore not included lane");

        NewspaperSummary.Lane pausedWinner = new NewspaperSummary.Lane(
                "Tablet", "ans", "Done", 15000L, null, true, 0, false, null, true
        );
        check("Fastest: Tablet · 15.0 s · includes pause".equals(
                RaceLine.leader(List.of(pausedWinner))
        ), "leader should include pause suffix");

        check("".equals(RaceLine.leader(List.of(
                new NewspaperSummary.Lane("A", "ans", "Streaming…", null),
                new NewspaperSummary.Lane("B", "ans", "Thinking…", null)
        ))), "leader should return empty string when no done lane");

        String bar72 = RaceLine.bar(72, 684, 28);
        check(bar72.length() == 28, "bar length should equal cells");
        check(count(bar72, '■') == 3, "bar(72,684,28) should have 3 filled cells");
        check(count(bar72, '─') == 25, "bar(72,684,28) should have 25 empty cells");

        String bar684 = RaceLine.bar(684, 684, 28);
        check(bar684.length() == 28, "bar length should equal cells");
        check(count(bar684, '■') == 28, "bar(684,684,28) should be all filled");

        String bar1 = RaceLine.bar(1, 684, 28);
        check(bar1.length() == 28, "bar length should equal cells");
        check(count(bar1, '■') == 1, "bar(1,684,28) should have exactly one filled cell");

        String bar0 = RaceLine.bar(0, 684, 28);
        check(bar0.length() == 28, "bar length should equal cells");
        check(count(bar0, '■') == 0, "bar(0,684,28) should have no filled cells");
        check(count(bar0, '─') == 28, "bar(0,684,28) should be all empty");

        String barMax0 = RaceLine.bar(5, 0, 28);
        check(barMax0.length() == 28, "bar length should equal cells");
        check(count(barMax0, '■') == 0, "bar(5,0,28) should have no filled cells");
        check(count(barMax0, '─') == 28, "bar(5,0,28) should be all empty");

        check("".equals(RaceLine.bar(5, 5, 0)), "bar with zero cells should be empty string");

        check(RaceLine.maxWords(List.of(
                new NewspaperSummary.Lane("A", "ans", "Done", 1L, null, true, 72, false, null, false),
                new NewspaperSummary.Lane("B", "ans", "Done", 1L, null, false, 999, false, null, false),
                new NewspaperSummary.Lane("C", "ans", "Done", 1L, null, true, 684, false, null, false)
        )) == 684, "maxWords should ignore not included lanes");

        // A later lane that is faster wins; a tie keeps the first lane.
        equal("Fastest: Phone · 9.1 s", RaceLine.leader(List.of(macBook,
                new NewspaperSummary.Lane("Phone", "ans", "Done", 9100L))));
        equal("Fastest: MacBook · 28.4 s", RaceLine.leader(List.of(macBook,
                new NewspaperSummary.Lane("Phone", "ans", "Done", 28400L))));
        equal(27, count(RaceLine.bar(675, 684, 28), '■'));
        System.out.println("RaceLineTest: OK");
    }

    private static int count(String s, char ch) {
        int n = 0;
        for (int i = 0; i < s.length(); i++) {
            if (s.charAt(i) == ch) {
                n++;
            }
        }
        return n;
    }

    private static void check(boolean condition, String message) {
        if (!condition) {
            throw new AssertionError(message);
        }
    }

    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected=" + expected + " actual=" + actual);
        }
    }
}

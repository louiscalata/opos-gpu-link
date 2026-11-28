package os.opos.launcher;

import java.util.List;

public final class SpanStatsModelTest {
    public static void main(String[] args) {
        SpanStatsModel unknown = SpanStatsModel.of(-1, null, List.of(), 10L, false);
        check(unknown.heatText().isEmpty());
        equal(UiPalette.Tone.NEUTRAL.ordinal(), unknown.heatTone().ordinal());

        SpanStatsModel cool = SpanStatsModel.of(0, "USB OK", List.of(), 10L, false);
        check(!cool.heatText().isEmpty());
        equal(UiPalette.Tone.OK.ordinal(), cool.heatTone().ordinal());

        SpanStatsModel warm = SpanStatsModel.of(2, "USB OK", List.of(), 10L, false);
        equal(UiPalette.Tone.NEUTRAL.ordinal(), warm.heatTone().ordinal());

        SpanStatsModel hot = SpanStatsModel.of(4, "USB OK", List.of(), 10L, false);
        equal(UiPalette.Tone.ERROR.ordinal(), hot.heatTone().ordinal());

        SpanStatsModel link = SpanStatsModel.of(0, "  USB-C\nConnected  ", List.of(), 10L, false);
        check("USB-C Connected".equals(link.linkText()));
        equal(UiPalette.Tone.OK.ordinal(), link.linkTone().ordinal());

        SpanStatsModel linkNull = SpanStatsModel.of(0, null, List.of(), 10L, false);
        check(linkNull.linkText().isEmpty());
        equal(UiPalette.Tone.NEUTRAL.ordinal(), linkNull.linkTone().ordinal());

        List<SpanStatsModel.Lane> lanes = List.of(
                new SpanStatsModel.Lane("A", "Streaming…", 312),
                new SpanStatsModel.Lane("B", "Done", 7),
                new SpanStatsModel.Lane("C", "Failed", 0)
        );
        SpanStatsModel model = SpanStatsModel.of(0, "USB", lanes, 7L, true);

        equal(3, model.rowCount());
        check(model.rowWorking(0));
        check(model.rowWorkingLine(0).contains("312 words"));
        check(!model.rowWorkingLine(0).contains("▃"));
        check(model.rowWorkingLine(1).isEmpty());
        equal(UiPalette.Tone.ERROR.ordinal(), model.rowTone(2).ordinal());
        check(model.anyWorking());

        SpanStatsModel same = SpanStatsModel.of(0, "USB", lanes, 7L, true);
        check(model.sameAs(same));
        check(!model.sameAs(null));

        // Reduced motion: a new tick changes nothing, so no redraw.
        check(model.sameAs(SpanStatsModel.of(0, "USB", lanes, 8L, true)));
        // Motion on: the spinner bar moves with the tick, and the dot dims after four ticks.
        SpanStatsModel moving = SpanStatsModel.of(0, "USB", lanes, 7L, false);
        SpanStatsModel moved = SpanStatsModel.of(0, "USB", lanes, 8L, false);
        check(!moving.sameAs(moved));
        check(!moving.rowWorkingLine(0).equals(moved.rowWorkingLine(0)));
        check(moving.rowDotBright(0) != SpanStatsModel.of(0, "USB", lanes, 3L, false).rowDotBright(0));
        check(!moving.rowDotBright(1));

        boolean threw = false;
        try {
            model.rowName(99);
        } catch (IndexOutOfBoundsException expected) {
            threw = true;
        }
        check(threw);

        System.out.println("SpanStatsModelTest: OK");
    }

    private static void check(boolean condition) {
        if (!condition) {
            throw new AssertionError();
        }
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) {
            throw new AssertionError("expected=" + expected + " actual=" + actual);
        }
    }
}

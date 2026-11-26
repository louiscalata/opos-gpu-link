package os.opos.launcher;

import java.util.List;

/** Stage-readable race figures for the TONIGHT card: the leader line and word bars. */
final class RaceLine {
    static final int CELLS = 28;

    private RaceLine() {
    }

    /**
     * The race headline under TONIGHT, e.g. "Fastest so far: MacBook · 28.4 s". Only included
     * lanes that are Done with a measured time count; ties go to the first lane. Same words
     * as the Summary, so the two never disagree. Empty until a lane qualifies.
     */
    static String leader(List<NewspaperSummary.Lane> lanes) {
        if (lanes == null || lanes.isEmpty()) {
            return "";
        }

        NewspaperSummary.Lane winner = null;
        Long bestElapsed = null;
        boolean anyStillGoing = false;

        for (NewspaperSummary.Lane lane : lanes) {
            if (lane == null || !lane.included) {
                continue;
            }
            if (NewspaperSummary.stillGoing(lane)) {
                anyStillGoing = true;
            }
            if (lane.state != null && lane.state.startsWith("Done") && lane.elapsedMs != null) {
                if (bestElapsed == null || lane.elapsedMs < bestElapsed) {
                    bestElapsed = lane.elapsedMs;
                    winner = lane;
                }
            }
        }

        if (winner == null) {
            return "";
        }

        StringBuilder sb = new StringBuilder();
        sb.append(anyStillGoing ? "Fastest so far: " : "Fastest: ");
        sb.append(winner.label);
        sb.append(" · ");
        sb.append(NewspaperSummary.seconds(winner.elapsedMs));
        if (winner.includesPause) {
            sb.append(" · includes pause");
        }
        return sb.toString();
    }

    /**
     * A monospace bar of words so far against the longest lane: filled cells then a hairline.
     * Any lane with words shows at least one cell, so a started lane never looks empty.
     */
    static String bar(int words, int maxWords, int cells) {
        if (cells <= 0) {
            return "";
        }
        if (words <= 0 || maxWords <= 0) {
            return repeat('─', cells);
        }

        long filled = Math.round((double) cells * (double) words / (double) maxWords);
        if (filled < 0) {
            filled = 0;
        }
        if (filled > cells) {
            filled = cells;
        }
        if (filled == 0 && words > 0) {
            filled = 1;
        }

        // Only the longest lane fills the bar, so a close second never looks tied.
        if (words < maxWords && filled >= cells) {
            filled = cells - 1;
        }

        int full = (int) filled;
        return repeat('■', full) + repeat('─', cells - full);
    }

    /** Largest words among included lanes, 0 if none. */
    static int maxWords(List<NewspaperSummary.Lane> lanes) {
        int max = 0;
        if (lanes == null) {
            return 0;
        }
        for (NewspaperSummary.Lane lane : lanes) {
            if (lane != null && lane.included && lane.words > max) {
                max = lane.words;
            }
        }
        return max;
    }

    private static String repeat(char ch, int count) {
        if (count <= 0) {
            return "";
        }
        StringBuilder sb = new StringBuilder(count);
        for (int i = 0; i < count; i++) {
            sb.append(ch);
        }
        return sb.toString();
    }
}

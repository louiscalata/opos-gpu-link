package os.opos.launcher;

import java.util.ArrayList;
import java.util.List;

/**
 * Immutable span stats snapshot.
 */
final class SpanStatsModel {
    static final class Lane {
        final String name;
        final String state;
        final int words;

        Lane(String name, String state, int words) {
            this.name = name == null ? "" : name;
            this.state = state == null ? "" : state;
            this.words = words;
        }
    }

    private final int heatStatus;
    private final String linkLabel;
    private final List<Lane> lanes;
    private final long workingTick;
    private final boolean reducedMotion;

    private SpanStatsModel(int heatStatus, String linkLabel, List<Lane> lanes, long workingTick, boolean reducedMotion) {
        this.heatStatus = heatStatus;
        this.linkLabel = linkLabel;
        this.lanes = lanes;
        this.workingTick = workingTick;
        this.reducedMotion = reducedMotion;
    }

    static SpanStatsModel of(int heatStatus, String linkLabel, List<Lane> lanes, long workingTick, boolean reducedMotion) {
        List<Lane> copy = lanes == null ? new ArrayList<Lane>() : new ArrayList<Lane>(lanes);
        return new SpanStatsModel(heatStatus, linkLabel, copy, workingTick, reducedMotion);
    }

    String heatText() {
        return HeatMeter.known(heatStatus) ? HeatMeter.label(heatStatus, false) : "";
    }

    UiPalette.Tone heatTone() {
        return HeatMeter.known(heatStatus) ? HeatMeter.tone(heatStatus) : UiPalette.Tone.NEUTRAL;
    }

    String linkText() {
        if (linkLabel == null) {
            return "";
        }
        return linkLabel.replace('\n', ' ').trim();
    }

    UiPalette.Tone linkTone() {
        return UiPalette.tone(linkText());
    }

    int rowCount() {
        return lanes.size();
    }

    String rowName(int index) {
        return lane(index).name;
    }

    String rowState(int index) {
        return lane(index).state;
    }

    UiPalette.Tone rowTone(int index) {
        return UiPalette.tone(rowState(index));
    }

    boolean rowWorking(int index) {
        return WorkingIndicator.working(rowState(index));
    }

    String rowWorkingLine(int index) {
        if (!rowWorking(index)) {
            return "";
        }
        return WorkingIndicator.line(workingTick, lane(index).words, reducedMotion, false);
    }

    boolean rowDotBright(int index) {
        return rowWorking(index) && WorkingIndicator.dotBright(workingTick, reducedMotion);
    }

    boolean anyWorking() {
        for (int i = 0; i < lanes.size(); i++) {
            if (rowWorking(i)) {
                return true;
            }
        }
        return false;
    }

    boolean sameAs(SpanStatsModel other) {
        if (other == null) {
            return false;
        }
        if (!heatText().equals(other.heatText())) {
            return false;
        }
        if (heatTone() != other.heatTone()) {
            return false;
        }
        if (!linkText().equals(other.linkText())) {
            return false;
        }
        if (linkTone() != other.linkTone()) {
            return false;
        }
        if (rowCount() != other.rowCount()) {
            return false;
        }
        for (int i = 0; i < rowCount(); i++) {
            if (!rowName(i).equals(other.rowName(i))) {
                return false;
            }
            if (!rowState(i).equals(other.rowState(i))) {
                return false;
            }
            if (rowTone(i) != other.rowTone(i)) {
                return false;
            }
            if (rowWorking(i) != other.rowWorking(i)) {
                return false;
            }
            if (!rowWorkingLine(i).equals(other.rowWorkingLine(i))
                    || rowDotBright(i) != other.rowDotBright(i)) {
                return false;
            }
        }
        return true;
    }

    private Lane lane(int index) {
        if (index < 0 || index >= lanes.size()) {
            throw new IndexOutOfBoundsException("row index: " + index);
        }
        return lanes.get(index);
    }
}

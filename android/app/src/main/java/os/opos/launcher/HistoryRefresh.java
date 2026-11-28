package os.opos.launcher;

import java.util.ArrayList;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * Host-testable History open, refresh-payload and link rules. The models keep no
 * chat history, so a refresh must resend the original prompt, never a bare
 * "again". The new run is a separate issue linked to the original.
 */
final class HistoryRefresh {
    private HistoryRefresh() {}

    /** The issue opened by a tap on a History row; null if the id is unknown. */
    static HistoryStore.Issue open(List<HistoryStore.Issue> issues, String id) {
        if (issues == null || id == null || id.isEmpty()) return null;
        for (HistoryStore.Issue issue : issues) {
            if (id.equals(issue.id)) return issue;
        }
        return null;
    }

    /**
     * The exact prompt a Refresh button sends through the normal ask path.
     * Empty when the saved question is missing or is only a bare follow-up.
     */
    static String payload(HistoryStore.Issue issue) {
        if (issue == null) return "";
        String question = FollowUpPolicy.originalQuestion(issue.question, "");
        return FollowUpPolicy.bareFollowUp(question) ? "" : question;
    }

    static boolean canRefresh(HistoryStore.Issue issue) {
        return !payload(issue).isEmpty();
    }

    /** The original issue id a refresh should link to. */
    static String rootId(HistoryStore.Issue issue) {
        if (issue == null) return "";
        return issue.sourceId.isEmpty() ? issue.id : issue.sourceId;
    }

    static boolean linked(HistoryStore.Issue original, HistoryStore.Issue refresh) {
        if (original == null || refresh == null) return false;
        if (original.id.equals(refresh.id)) return false;
        if (!rootId(original).equals(refresh.sourceId) && !original.id.equals(refresh.sourceId)) {
            return false;
        }
        String expected = payload(original);
        return !expected.isEmpty() && expected.equals(payload(refresh));
    }

    static boolean originalPreserved(HistoryStore.Issue before, HistoryStore.Issue after) {
        if (before == null || after == null || !before.id.equals(after.id)) return false;
        return before.askedAtMs == after.askedAtMs
                && before.question.equals(after.question)
                && before.timing.equals(after.timing)
                && before.elapsed.equals(after.elapsed)
                && before.sourceId.equals(after.sourceId)
                && before.lanes.size() == after.lanes.size();
    }

    static HistoryStore.Issue originalOf(List<HistoryStore.Issue> issues, HistoryStore.Issue issue) {
        return open(issues, rootId(issue));
    }

    /** Newest later run of this original; the list is assumed newest first. */
    static HistoryStore.Issue latestRefresh(List<HistoryStore.Issue> issues, HistoryStore.Issue issue) {
        if (issues == null || issue == null) return null;
        String root = rootId(issue);
        for (HistoryStore.Issue candidate : issues) {
            if (!candidate.id.equals(root) && root.equals(candidate.sourceId)) return candidate;
        }
        return null;
    }

    static final class LaneCompare {
        final String pane, thenLabel, nowLabel;
        final String thenState, nowState, thenText, nowText;
        final long thenElapsedMs, nowElapsedMs;
        final UiPalette.Tone thenTone, nowTone;
        final boolean presentThen, presentNow;

        LaneCompare(String pane, String thenLabel, String nowLabel,
                    String thenState, String thenText, long thenElapsedMs, boolean presentThen,
                    String nowState, String nowText, long nowElapsedMs, boolean presentNow) {
            this.pane = pane;
            this.thenLabel = thenLabel;
            this.nowLabel = nowLabel;
            this.thenState = thenState;
            this.thenText = thenText;
            this.thenElapsedMs = thenElapsedMs;
            this.presentThen = presentThen;
            this.nowState = nowState;
            this.nowText = nowText;
            this.nowElapsedMs = nowElapsedMs;
            this.presentNow = presentNow;
            this.thenTone = presentThen ? UiPalette.tone(thenState) : UiPalette.Tone.NEUTRAL;
            this.nowTone = presentNow ? UiPalette.tone(nowState) : UiPalette.Tone.NEUTRAL;
        }
    }

    static List<LaneCompare> compare(HistoryStore.Issue thenIssue, HistoryStore.Issue nowIssue) {
        List<LaneCompare> rows = new ArrayList<>();
        Set<String> panes = new LinkedHashSet<>();
        if (thenIssue != null) for (HistoryStore.Lane lane : thenIssue.lanes) panes.add(lane.pane);
        if (nowIssue != null) for (HistoryStore.Lane lane : nowIssue.lanes) panes.add(lane.pane);
        for (String pane : panes) {
            HistoryStore.Lane thenLane = lane(thenIssue, pane);
            HistoryStore.Lane nowLane = lane(nowIssue, pane);
            rows.add(new LaneCompare(pane, label(thenLane, pane), label(nowLane, pane),
                    thenLane == null ? "" : thenLane.state,
                    thenLane == null ? "" : thenLane.text,
                    thenLane == null ? 0 : thenLane.elapsedMs,
                    thenLane != null,
                    nowLane == null ? "" : nowLane.state,
                    nowLane == null ? "" : nowLane.text,
                    nowLane == null ? 0 : nowLane.elapsedMs,
                    nowLane != null));
        }
        return rows;
    }

    private static String label(HistoryStore.Lane lane, String pane) {
        if (lane == null) return "";
        return lane.label.isEmpty() ? PaneKeys.fallbackLabel(pane) : lane.label;
    }

    private static HistoryStore.Lane lane(HistoryStore.Issue issue, String pane) {
        if (issue == null) return null;
        for (HistoryStore.Lane lane : issue.lanes) {
            if (pane.equals(lane.pane)) return lane;
        }
        return null;
    }
}

package os.opos.launcher;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/** Maps a saved issue into read-only newspaper text, never a live backend request. */
final class BackIssue {
    final String headline, timing, elapsed, elapsedLabel, answeredBy;
    final List<HistoryStore.Lane> lanes;

    private BackIssue(String headline, String timing, String elapsed,
                      String elapsedLabel, String answeredBy,
                      List<HistoryStore.Lane> lanes) {
        this.headline = headline;
        this.timing = timing;
        this.elapsed = elapsed;
        this.elapsedLabel = elapsedLabel;
        this.answeredBy = answeredBy;
        this.lanes = Collections.unmodifiableList(new ArrayList<>(lanes));
    }

    static BackIssue from(HistoryStore.Issue issue) {
        List<String> answered = new ArrayList<>();
        List<HistoryStore.Lane> displayed = new ArrayList<>();
        boolean legacy = !issue.pauseProvenanceKnown;
        for (HistoryStore.Lane lane : issue.lanes) {
            if (lane.state.startsWith("Done") || !lane.text.trim().isEmpty()) {
                answered.add(lane.label);
            }
            displayed.add(legacy ? lane.withState(
                    AnswerTimingPolicy.legacyDoneLabel(lane.state, lane.elapsedMs)) : lane);
        }
        String timing = legacy && !issue.timing.isEmpty()
                ? "Saved model times may include a cable pause\n" + issue.timing
                : issue.timing;
        String elapsedLabel = legacy ? AnswerTimingPolicy.LEGACY_WALL
                : AnswerTimingPolicy.overallLabel(issue.pauseObserved);
        return new BackIssue("You asked: " + issue.question, timing,
                issue.elapsed, elapsedLabel,
                answered.isEmpty() ? "No answers" : String.join(", ", answered),
                displayed);
    }
}

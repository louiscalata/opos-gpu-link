package os.opos.launcher;

import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Local-only Send gating. An uncertain POST cannot be made safe by repeating it. */
final class AskRecoveryPolicy {
    static final long ID_WAIT_MS = 20_000;

    enum AskKind { SEND, RETRY }
    enum Next { POST, BIND, HOLD }

    static final class Answer {
        final String id, question, state;
        final double asked;

        Answer(String id, String question, double asked, String state) {
            this.id = id == null ? "" : id;
            this.question = question == null ? "" : question;
            this.asked = asked;
            this.state = state == null ? "" : state;
        }
    }

    static final class Attempt {
        final String question;
        final Map<String, Answer> before;

        Attempt(String question, List<String> requested, Map<String, Answer> before) {
            if (question == null || question.isEmpty() || requested == null
                    || requested.isEmpty() || before == null) {
                throw new IllegalArgumentException("Incomplete ask baseline");
            }
            this.question = question;
            Map<String, Answer> copied = new LinkedHashMap<>();
            for (String pane : requested) {
                if (pane == null || copied.containsKey(pane) || !before.containsKey(pane)
                        || before.get(pane) == null) {
                    throw new IllegalArgumentException("Incomplete requested pane");
                }
                copied.put(pane, before.get(pane));
            }
            this.before = Collections.unmodifiableMap(copied);
        }
    }

    static final class Decision {
        final Next next;
        final List<String> advancedPanes;
        final boolean complete;

        private Decision(Next next, List<String> advancedPanes, boolean complete) {
            this.next = next;
            this.advancedPanes = Collections.unmodifiableList(advancedPanes);
            this.complete = complete;
        }
    }

    private static final class IdlessOpen {
        final String question;
        final double asked;
        final long firstSeenMs;

        IdlessOpen(String question, double asked, long firstSeenMs) {
            this.question = question;
            this.asked = asked;
            this.firstSeenMs = firstSeenMs;
        }
    }

    private final Map<String, IdlessOpen> firstSeenIdlessOpen = new HashMap<>();
    private Attempt uncertain;
    private boolean unknownUncertain;

    boolean blocksOpen(String pane, boolean open, String id,
                       String question, double asked, long elapsedMs) {
        if (!open || (id != null && !id.isEmpty())) {
            firstSeenIdlessOpen.remove(pane);
            return open;
        }
        String currentQuestion = question == null ? "" : question;
        IdlessOpen observed = firstSeenIdlessOpen.get(pane);
        if (observed == null || elapsedMs < observed.firstSeenMs
                || !currentQuestion.equals(observed.question)
                || Double.compare(asked, observed.asked) != 0) {
            observed = new IdlessOpen(currentQuestion, asked, elapsedMs);
            firstSeenIdlessOpen.put(pane, observed);
        }
        return elapsedMs - observed.firstSeenMs < ID_WAIT_MS;
    }

    void markUncertain(Attempt attempt) {
        uncertain = attempt;
        unknownUncertain = false;
    }

    void restoreUnknownUncertain() {
        uncertain = null;
        unknownUncertain = true;
    }

    boolean unresolved() {
        return uncertain != null || unknownUncertain;
    }

    Decision beforeAsk(AskKind kind, Map<String, Answer> fresh, boolean usable) {
        if (kind == null) throw new IllegalArgumentException("Ask kind required");
        // An ordinary Send and Try again have the same duplicate-POST boundary.
        if (!unresolved()) return new Decision(Next.POST, Collections.emptyList(), false);
        if (!usable || fresh == null || uncertain == null) {
            return new Decision(Next.HOLD, Collections.emptyList(), false);
        }
        List<String> advanced = new ArrayList<>();
        for (Map.Entry<String, Answer> entry : uncertain.before.entrySet()) {
            Answer previous = entry.getValue();
            Answer current = fresh.get(entry.getKey());
            if (current != null && !current.id.isEmpty()
                    && !current.id.equals(previous.id)
                    && uncertain.question.equals(current.question)
                    && Double.isFinite(current.asked) && current.asked > 0
                    && current.asked >= previous.asked && !current.state.isEmpty()) {
                advanced.add(entry.getKey());
            }
        }
        return advanced.isEmpty()
                ? new Decision(Next.HOLD, advanced, false)
                : new Decision(Next.BIND, advanced,
                        advanced.size() == uncertain.before.size());
    }

    void resolve() {
        uncertain = null;
        unknownUncertain = false;
    }

    void resetLocal() {
        resolve();
        // Keep observed ID-less ages. Reset must not restart their 20 s Send block.
    }
}

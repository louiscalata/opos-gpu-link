package os.opos.launcher;

import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Bounded app-private history. Each issue is a separate preference value. */
final class HistoryStore {
    static final int MAX_ISSUES = 50;
    static final int MAX_ISSUE_BYTES = 200_000;
    private static final int VERSION = 3;
    private static final int VERSION_PAUSE = 2;
    private static final int LEGACY_VERSION = 1;
    private static final String INDEX = "history_index_v1";
    private static final String PREFIX = "history_issue_v1_";
    static final String SUPPRESSED = "history_suppressed_issue_id";

    interface Store {
        String get(String key);
        void update(Map<String, String> values, List<String> removals);
    }

    static final class Lane {
        final String pane, label, maker, where, state, text;
        final long elapsedMs;
        final boolean truncated;

        Lane(String pane, String label, String maker, String where,
             String state, String text, long elapsedMs) {
            this(pane, label, maker, where, state, text, elapsedMs, false);
        }

        private Lane(String pane, String label, String maker, String where,
                     String state, String text, long elapsedMs, boolean truncated) {
            if (!PaneKeys.valid(pane)) throw new IllegalArgumentException("Unknown pane");
            this.pane = pane;
            this.label = limited(label, 1024);
            this.maker = limited(maker, 1024);
            this.where = limited(where, 1024);
            this.state = limited(state, 1024);
            this.text = safe(text);
            this.elapsedMs = elapsedMs;
            this.truncated = truncated;
        }

        Lane withText(String replacement) {
            return new Lane(pane, label, maker, where, state, replacement, elapsedMs, true);
        }

        Lane withState(String replacement) {
            return new Lane(pane, label, maker, where, replacement, text, elapsedMs, truncated);
        }
    }

    static final class Issue {
        final String id, question, timing, elapsed, sourceId;
        final long askedAtMs;
        final List<Lane> lanes;
        final boolean pauseProvenanceKnown, pauseObserved;

        Issue(String id, long askedAtMs, String question, String timing,
              String elapsed, List<Lane> lanes) {
            this(id, askedAtMs, question, timing, elapsed, lanes, true, false, "");
        }

        Issue(String id, long askedAtMs, String question, String timing,
              String elapsed, List<Lane> lanes, boolean pauseObserved) {
            this(id, askedAtMs, question, timing, elapsed, lanes, true, pauseObserved, "");
        }

        Issue(String id, long askedAtMs, String question, String timing,
              String elapsed, List<Lane> lanes, boolean pauseObserved, String sourceId) {
            this(id, askedAtMs, question, timing, elapsed, lanes, true, pauseObserved, sourceId);
        }

        private Issue(String id, long askedAtMs, String question, String timing,
                      String elapsed, List<Lane> lanes, boolean pauseProvenanceKnown,
                      boolean pauseObserved, String sourceId) {
            if (id == null || !id.matches("[0-9]{1,19}")) {
                throw new IllegalArgumentException("Invalid issue ID");
            }
            this.id = id;
            this.askedAtMs = askedAtMs;
            this.question = limited(question, 4096);
            this.timing = limited(timing, 2048);
            this.elapsed = limited(elapsed, 128);
            this.lanes = Collections.unmodifiableList(new ArrayList<>(lanes));
            this.pauseProvenanceKnown = pauseProvenanceKnown;
            this.pauseObserved = pauseObserved;
            String link = sourceId == null ? "" : sourceId.trim();
            this.sourceId = link.matches("[0-9]{1,19}") && !link.equals(id) ? link : "";
        }

        Issue withLanes(List<Lane> replacement) {
            return new Issue(id, askedAtMs, question, timing, elapsed, replacement,
                    pauseProvenanceKnown, pauseObserved, sourceId);
        }
    }

    private final Store store;

    HistoryStore(Store store) { this.store = store; }

    void upsert(Issue issue) {
        Issue fitted = fit(issue);
        byte[] bytes = encode(fitted);
        String payload = Base64.getEncoder().encodeToString(bytes);
        if (payload.getBytes(StandardCharsets.UTF_8).length > MAX_ISSUE_BYTES) {
            throw new IllegalArgumentException("Issue exceeds 200 KB");
        }
        List<String> ids = ids();
        ids.remove(issue.id);
        ids.add(0, issue.id);
        ids.sort((a, b) -> a.length() == b.length()
                ? b.compareTo(a) : Integer.compare(b.length(), a.length()));
        List<String> removals = new ArrayList<>();
        while (ids.size() > MAX_ISSUES) removals.add(PREFIX + ids.remove(ids.size() - 1));
        Map<String, String> writes = new HashMap<>();
        writes.put(PREFIX + issue.id, payload);
        writes.put(INDEX, String.join("\n", ids));
        store.update(writes, removals);
    }

    List<Issue> list() {
        List<Issue> result = new ArrayList<>();
        for (String id : ids()) {
            String payload = store.get(PREFIX + id);
            if (payload == null) continue;
            try {
                if (payload.getBytes(StandardCharsets.UTF_8).length > MAX_ISSUE_BYTES) continue;
                byte[] bytes = Base64.getDecoder().decode(payload);
                if (bytes.length > MAX_ISSUE_BYTES) continue;
                Issue issue = decode(bytes);
                if (id.equals(issue.id)) result.add(issue);
            } catch (IllegalArgumentException | IOException ignored) {
                // A damaged local record does not hide the remaining issues.
            }
        }
        return result;
    }

    boolean contains(String id) { return ids().contains(id); }

    void clear() {
        clear("");
    }

    void clear(String suppressedId) {
        List<String> removals = new ArrayList<>();
        for (String id : ids()) removals.add(PREFIX + id);
        removals.add(INDEX);
        Map<String, String> writes = new HashMap<>();
        if (suppressedId != null && suppressedId.matches("[0-9]{1,19}")) {
            writes.put(SUPPRESSED, suppressedId);
        } else removals.add(SUPPRESSED);
        store.update(writes, removals);
    }

    private List<String> ids() {
        String index = store.get(INDEX);
        List<String> result = new ArrayList<>();
        if (index == null || index.isEmpty()) return result;
        for (String id : index.split("\n")) {
            if (result.size() >= MAX_ISSUES || !id.matches("[0-9]{1,19}")
                    || result.contains(id)) continue;
            result.add(id);
        }
        return result;
    }

    private static Issue fit(Issue issue) {
        Issue current = issue;
        byte[] bytes = encode(current);
        while (Base64.getEncoder().encodeToString(bytes).length() > MAX_ISSUE_BYTES) {
            int longest = -1;
            for (int i = 0; i < current.lanes.size(); i++) {
                if (longest < 0 || current.lanes.get(i).text.length()
                        > current.lanes.get(longest).text.length()) longest = i;
            }
            if (longest < 0 || current.lanes.get(longest).text.isEmpty()) {
                throw new IllegalArgumentException("Issue metadata exceeds 200 KB");
            }
            List<Lane> trimmed = new ArrayList<>(current.lanes);
            String text = trimmed.get(longest).text;
            int excess = Base64.getEncoder().encodeToString(bytes).length()
                    - MAX_ISSUE_BYTES;
            int cut = Math.min(text.length(), Math.max(1, excess));
            int end = text.length() - cut;
            if (end > 0 && Character.isHighSurrogate(text.charAt(end - 1))) end--;
            trimmed.set(longest, trimmed.get(longest).withText(text.substring(0, end)));
            current = current.withLanes(trimmed);
            bytes = encode(current);
        }
        return current;
    }

    private static byte[] encode(Issue issue) {
        try {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            DataOutputStream output = new DataOutputStream(bytes);
            output.writeInt(VERSION);
            writeString(output, issue.id);
            output.writeLong(issue.askedAtMs);
            writeString(output, issue.question);
            writeString(output, issue.timing);
            writeString(output, issue.elapsed);
            output.writeBoolean(issue.pauseProvenanceKnown);
            output.writeBoolean(issue.pauseObserved);
            output.writeInt(issue.lanes.size());
            for (Lane lane : issue.lanes) {
                writeString(output, lane.pane);
                writeString(output, lane.label);
                writeString(output, lane.maker);
                writeString(output, lane.where);
                writeString(output, lane.state);
                writeString(output, lane.text);
                output.writeLong(lane.elapsedMs);
                output.writeBoolean(lane.truncated);
            }
            writeString(output, issue.sourceId);
            output.flush();
            return bytes.toByteArray();
        } catch (IOException impossible) {
            throw new AssertionError(impossible);
        }
    }

    private static Issue decode(byte[] bytes) throws IOException {
        DataInputStream input = new DataInputStream(new ByteArrayInputStream(bytes));
        int version = input.readInt();
        if (version != VERSION && version != VERSION_PAUSE && version != LEGACY_VERSION) {
            throw new IOException("Unknown history version");
        }
        String id = readString(input);
        long askedAtMs = input.readLong();
        String question = readString(input);
        String timing = readString(input);
        String elapsed = readString(input);
        boolean pauseProvenanceKnown = false;
        boolean pauseObserved = false;
        if (version == VERSION || version == VERSION_PAUSE) {
            pauseProvenanceKnown = input.readBoolean();
            pauseObserved = input.readBoolean();
        }
        int count = input.readInt();
        if (count < 0 || count > 9) throw new IOException("Invalid lane count");
        List<Lane> lanes = new ArrayList<>();
        for (int i = 0; i < count; i++) {
            lanes.add(new Lane(readString(input), readString(input), readString(input),
                    readString(input), readString(input), readString(input), input.readLong(),
                    input.readBoolean()));
        }
        String sourceId = "";
        if (version == VERSION) sourceId = readString(input);
        if (input.available() != 0) throw new IOException("Trailing history bytes");
        return new Issue(id, askedAtMs, question, timing, elapsed, lanes,
                pauseProvenanceKnown, pauseObserved, sourceId);
    }

    private static void writeString(DataOutputStream output, String value) throws IOException {
        byte[] bytes = value.getBytes(StandardCharsets.UTF_8);
        output.writeInt(bytes.length);
        output.write(bytes);
    }

    private static String readString(DataInputStream input) throws IOException {
        int length = input.readInt();
        if (length < 0 || length > MAX_ISSUE_BYTES || length > input.available()) {
            throw new IOException("Invalid history string length");
        }
        byte[] bytes = new byte[length];
        input.readFully(bytes);
        return new String(bytes, StandardCharsets.UTF_8);
    }

    private static String safe(String value) { return value == null ? "" : value; }

    private static String limited(String value, int maxBytes) {
        String text = safe(value);
        if (text.getBytes(StandardCharsets.UTF_8).length <= maxBytes) return text;
        int end = text.length();
        while (end > 0 && text.substring(0, end).getBytes(StandardCharsets.UTF_8).length > maxBytes) {
            end = Math.max(0, end - Math.max(1, (end * 2) / 3));
        }
        if (end > 0 && end < text.length() && Character.isLowSurrogate(text.charAt(end))) end--;
        if (end > 0 && end < text.length() && Character.isHighSurrogate(text.charAt(end - 1))) end--;
        while (end < text.length()) {
            int next = end + Character.charCount(text.codePointAt(end));
            if (text.substring(0, next).getBytes(StandardCharsets.UTF_8).length > maxBytes) break;
            end = next;
        }
        return text.substring(0, end);
    }
}

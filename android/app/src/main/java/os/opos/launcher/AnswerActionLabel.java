package os.opos.launcher;

/** A spoken answer action always has a useful target, even before its heading arrives. */
final class AnswerActionLabel {
    private AnswerActionLabel() {}

    static String target(CharSequence heading) {
        String label = heading == null ? "" : heading.toString().trim();
        return label.isEmpty() ? "this model" : label;
    }
}

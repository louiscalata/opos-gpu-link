package os.opos.launcher;

/** Selects the failed-answer label without changing the answer state. */
final class AnswerFailureLabel {
    private AnswerFailureLabel() {}

    static int resource(boolean gpu, String text) {
        return resource(gpu, text, null);
    }

    static int resource(boolean gpu, String text, String error) {
        if ("garbled".equals(error)) return R.string.answer_garbled;
        if (text != null && !text.trim().isEmpty()) {
            return gpu ? R.string.gpu_failed_partial : R.string.phone_failed_partial;
        }
        return gpu ? R.string.gpu_failed : R.string.phone_failed;
    }
}

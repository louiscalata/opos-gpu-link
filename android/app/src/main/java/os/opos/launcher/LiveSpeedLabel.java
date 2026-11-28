package os.opos.launcher;

/** Only the active, visible answer may show its reported single-run speed. */
final class LiveSpeedLabel {
    private LiveSpeedLabel() {}

    static String text(Object reported, String state, boolean answerVisible) {
        if (!answerVisible || !"answering".equals(state) || !(reported instanceof Number)) {
            return "";
        }
        double value = ((Number) reported).doubleValue();
        String figure = reported.toString();
        if (!Double.isFinite(value) || value <= 0 || figure.length() > 10) return "";
        return figure + " tokens a second · this run";
    }
}

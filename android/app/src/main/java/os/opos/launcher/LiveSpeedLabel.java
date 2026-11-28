package os.opos.launcher;

/** Only the active, visible answer may show its reported single-run speed. */
final class LiveSpeedLabel {
    private LiveSpeedLabel() {}

    static String text(Object reported, String state, boolean answerVisible,
                       String displayedState, String streamingLabel) {
        if (!answerVisible || streamingLabel == null || !streamingLabel.equals(displayedState)
                || !"answering".equals(state)
                || !(reported instanceof Number)) {
            return "";
        }
        double value = ((Number) reported).doubleValue();
        String figure = reported.toString();
        if (!Double.isFinite(value) || value <= 0 || figure.length() > 10
                || figure.indexOf('E') >= 0 || figure.indexOf('e') >= 0) return "";
        return figure + (value == 1d ? " token" : " tokens") + " a second · this run";
    }
}

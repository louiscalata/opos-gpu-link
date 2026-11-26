package os.opos.launcher;

/** Read-only classification of the phone's configured screen-off timeout. */
final class ScreenTimeoutPreflight {
    static final int TEN_MINUTES_MS = 10 * 60 * 1000;

    private ScreenTimeoutPreflight() {}

    static Result assess(int timeoutMs) {
        if (timeoutMs <= 0) return new Result(false, false, "");
        int minutes = timeoutMs / 60000;
        int seconds = timeoutMs % 60000 / 1000;
        String duration;
        if (minutes == 0 && seconds == 0) duration = "less than 1 sec";
        else if (minutes == 0) duration = seconds + " sec";
        else if (seconds == 0) duration = minutes + " min";
        else duration = minutes + " min " + seconds + " sec";
        return new Result(true, timeoutMs < TEN_MINUTES_MS, duration);
    }

    static final class Result {
        final boolean known;
        final boolean shorterThanTenMinutes;
        final String duration;

        private Result(boolean known, boolean shorterThanTenMinutes, String duration) {
            this.known = known;
            this.shorterThanTenMinutes = shorterThanTenMinutes;
            this.duration = duration;
        }
    }
}

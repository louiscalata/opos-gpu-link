package os.opos.launcher;

/** Compact chrome sizes that leave the results scroll room above the keyboard. */
final class CoverLayoutPolicy {
    static final int MASTHEAD_DP = 62;
    static final int COMPOSER_ROW_DP = 64;
    static final int WIDE_COMPOSER_ROW_DP = 52;
    static final int KEYBOARD_COMPOSER_ROW_DP = 48;
    static final int MIN_RESULTS_DP = 64;
    static final int TITLE_ROW_DP = 54;

    private CoverLayoutPolicy() {}

    static int mastheadHeightDp(boolean compact, boolean keyboardVisible) {
        return compact && keyboardVisible ? 0 : MASTHEAD_DP;
    }

    static int composerRowHeightDp(boolean compact, boolean keyboardVisible) {
        return compact && keyboardVisible ? KEYBOARD_COMPOSER_ROW_DP
                : COMPOSER_ROW_DP;
    }

    static int composerRowHeightDp(boolean compact, boolean keyboardVisible, boolean wide) {
        return wide ? WIDE_COMPOSER_ROW_DP : composerRowHeightDp(compact, keyboardVisible);
    }

    static int resultsSpaceDp(int viewportDp, int otherChromeDp,
                              boolean compact, boolean keyboardVisible) {
        return Math.max(0, viewportDp - otherChromeDp
                - mastheadHeightDp(compact, keyboardVisible)
                - composerRowHeightDp(compact, keyboardVisible));
    }

    static boolean showTitleRow(int currentResultsDp, boolean currentlyShown) {
        int resultsWithTitle = currentResultsDp
                - (currentlyShown ? 0 : TITLE_ROW_DP);
        return resultsWithTitle >= MIN_RESULTS_DP;
    }
}

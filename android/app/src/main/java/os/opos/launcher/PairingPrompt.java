package os.opos.launcher;

/**
 * Host-testable pairing-prompt decisions. The live prompt is a full-screen
 * modal so a pending request cannot be missed; typography stays on the
 * H5 + S5 + B5 system, with a larger tabular size for the six-digit code.
 */
final class PairingPrompt {
    static final int TIMEOUT_SECONDS = 60;
    static final int WARN_SECONDS = 10;
    static final int CODE_SP_INNER = 56;
    static final int CODE_SP_COVER = 36;
    static final int ALLOW_DP_INNER = 72;
    static final int ALLOW_DP_COVER = 56;
    static final int DENY_DP_INNER = 48;
    static final int DENY_DP_COVER = 44;
    static final int PAD_DP_INNER = 24;
    static final int PAD_DP_COVER = 12;

    private PairingPrompt() {}

    /** Group a six-digit code as "XXX XXX". Other text is trimmed and left as-is. */
    static String formatCode(String code) {
        if (code == null) return "";
        String digits = code.replace(" ", "").trim();
        if (!digits.matches("[0-9]{6}")) return code.trim();
        return digits.substring(0, 3) + " " + digits.substring(3);
    }

    static boolean validCode(String code) {
        if (code == null) return false;
        return code.replace(" ", "").trim().matches("[0-9]{6}");
    }

    /**
     * Snapshot {@code pending.seconds} is already ceil'd by the phone service.
     * Missing values stay -1 so the UI does not invent a countdown.
     */
    static int reportedSeconds(boolean present, int value) {
        if (!present) return -1;
        if (value < 0) return 0;
        if (value > TIMEOUT_SECONDS) return TIMEOUT_SECONDS;
        return value;
    }

    /**
     * Parse snapshot {@code pending.seconds}. A missing or null field stays -1
     * so the UI does not invent a countdown. Non-numeric values are ignored.
     */
    static int secondsFromField(boolean hasKey, boolean isNull, Object raw) {
        if (!hasKey || isNull || raw == null) return -1;
        if (raw instanceof Number) {
            return reportedSeconds(true, ((Number) raw).intValue());
        }
        if (raw instanceof String) {
            String text = ((String) raw).trim();
            if (text.matches("0|[1-9][0-9]*")) {
                try {
                    return reportedSeconds(true, Integer.parseInt(text));
                } catch (NumberFormatException ignored) {
                    return -1;
                }
            }
        }
        return -1;
    }

    static boolean hasCountdown(int seconds) {
        return seconds >= 0;
    }

    static boolean urgent(int seconds) {
        return hasCountdown(seconds) && seconds <= WARN_SECONDS;
    }

    static boolean expired(int seconds) {
        return hasCountdown(seconds) && seconds <= 0;
    }

    /** {@code expiredWord} is used at 0 s; otherwise {@code "%d s left"}. */
    static String countdownText(int seconds, String remainingTemplate, String expiredWord) {
        if (!hasCountdown(seconds)) return "";
        if (expired(seconds)) return expiredWord == null ? "" : expiredWord;
        return String.format(java.util.Locale.US, remainingTemplate, seconds);
    }

    /** First peek line for a heads-up notification: "738 414 · 45 s left". */
    static String headsUpLine(String formattedCode, int seconds,
                              String remainingTemplate, String expiredWord) {
        String code = formattedCode == null ? "" : formattedCode;
        String suffix = countdownText(seconds, remainingTemplate, expiredWord);
        if (suffix.isEmpty()) return code;
        return code.isEmpty() ? suffix : code + " · " + suffix;
    }

    static int codeSizeSp(boolean cover) {
        return cover ? CODE_SP_COVER : CODE_SP_INNER;
    }

    static int allowMinHeightDp(boolean cover) {
        return cover ? ALLOW_DP_COVER : ALLOW_DP_INNER;
    }

    static int denyMinHeightDp(boolean cover) {
        return cover ? DENY_DP_COVER : DENY_DP_INNER;
    }

    static int paddingDp(boolean cover) {
        return cover ? PAD_DP_COVER : PAD_DP_INNER;
    }

    /** A pending request uses the full-screen modal; a closed gate stays a banner. */
    static boolean showModal(boolean pending) {
        return pending;
    }

    static boolean showClosedBanner(boolean pending, boolean closed) {
        return !pending && closed;
    }
}

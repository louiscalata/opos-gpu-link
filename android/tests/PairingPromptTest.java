package os.opos.launcher;

public final class PairingPromptTest {
    public static void main(String[] args) {
        equal("738 414", PairingPrompt.formatCode("738414"));
        equal("738 414", PairingPrompt.formatCode("738 414"));
        equal("000 000", PairingPrompt.formatCode("000000"));
        equal("", PairingPrompt.formatCode(null));
        equal("", PairingPrompt.formatCode(""));
        equal("12", PairingPrompt.formatCode("12"));
        equal("abcdef", PairingPrompt.formatCode("abcdef"));
        check(PairingPrompt.validCode("738414"));
        check(PairingPrompt.validCode("738 414"));
        check(!PairingPrompt.validCode("73841"));
        check(!PairingPrompt.validCode(null));

        equal(-1, PairingPrompt.reportedSeconds(false, 60));
        equal(-1, PairingPrompt.reportedSeconds(false, 0));
        equal(0, PairingPrompt.reportedSeconds(true, -3));
        equal(60, PairingPrompt.reportedSeconds(true, 90));
        equal(45, PairingPrompt.reportedSeconds(true, 45));
        check(!PairingPrompt.hasCountdown(-1));
        check(PairingPrompt.hasCountdown(0));
        check(PairingPrompt.expired(0));
        check(!PairingPrompt.expired(-1));
        check(!PairingPrompt.expired(1));
        check(PairingPrompt.urgent(0));
        check(PairingPrompt.urgent(10));
        check(!PairingPrompt.urgent(11));
        check(!PairingPrompt.urgent(-1));

        equal("45 s left", PairingPrompt.countdownText(45, "%d s left", "Expired"));
        equal("1 s left", PairingPrompt.countdownText(1, "%d s left", "Expired"));
        equal("Expired", PairingPrompt.countdownText(0, "%d s left", "Expired"));
        equal("", PairingPrompt.countdownText(-1, "%d s left", "Expired"));

        equal(-1, PairingPrompt.secondsFromField(false, false, 60));
        equal(-1, PairingPrompt.secondsFromField(true, true, 60));
        equal(-1, PairingPrompt.secondsFromField(true, false, null));
        equal(-1, PairingPrompt.secondsFromField(true, false, "soon"));
        equal(45, PairingPrompt.secondsFromField(true, false, 45));
        equal(45, PairingPrompt.secondsFromField(true, false, Integer.valueOf(45)));
        equal(12, PairingPrompt.secondsFromField(true, false, "12"));
        equal(0, PairingPrompt.secondsFromField(true, false, -3));

        equal("738 414 · 45 s left",
                PairingPrompt.headsUpLine("738 414", 45, "%d s left", "Expired"));
        equal("738 414 · Expired",
                PairingPrompt.headsUpLine("738 414", 0, "%d s left", "Expired"));
        equal("738 414", PairingPrompt.headsUpLine("738 414", -1, "%d s left", "Expired"));
        equal("45 s left", PairingPrompt.headsUpLine("", 45, "%d s left", "Expired"));

        check(PairingPrompt.codeSizeSp(false) > PairingPrompt.codeSizeSp(true));
        check(PairingPrompt.codeSizeSp(false) >= 48);
        check(PairingPrompt.allowMinHeightDp(false) > PairingPrompt.denyMinHeightDp(false));
        // Side by side on the cover, so the two buttons share one height.
        check(PairingPrompt.allowMinHeightDp(true) == PairingPrompt.denyMinHeightDp(true));
        check(PairingPrompt.allowMinHeightDp(true) >= 48);
        check(PairingPrompt.denyMinHeightDp(true) >= 48);
        check(PairingPrompt.paddingDp(false) > PairingPrompt.paddingDp(true));

        check(PairingPrompt.showModal(true));
        check(!PairingPrompt.showModal(false));
        check(PairingPrompt.showClosedBanner(false, true));
        check(!PairingPrompt.showClosedBanner(true, true));
        check(!PairingPrompt.showClosedBanner(false, false));

        // Cover code at 36sp should fit "738 414" on the Flip cover (~374 dp).
        // 7 glyphs * 0.7 em is a conservative width for tabular figures.
        double coverCodeDp = 7 * 0.7 * PairingPrompt.codeSizeSp(true);
        check(coverCodeDp < 374);
        // Every pairing button is a 48 dp touch target, inner and cover.
        check(PairingPrompt.denyMinHeightDp(true) >= 48 && PairingPrompt.denyMinHeightDp(false) >= 48);
        check(PairingPrompt.allowMinHeightDp(true) >= 48);
        // Cover: buttons in one row and tight gaps so the disclosure clears the buttons.
        check(PairingPrompt.actionsSideBySide(true) && !PairingPrompt.actionsSideBySide(false));
        check(PairingPrompt.gapDp(true) < PairingPrompt.gapDp(false));

        System.out.println("PairingPromptTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

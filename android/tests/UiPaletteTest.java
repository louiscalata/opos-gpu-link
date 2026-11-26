package os.opos.launcher;

public final class UiPaletteTest {
    public static void main(String[] args) {
        equal(UiPalette.Theme.DARK, UiPalette.resolve("dark", false));
        equal(UiPalette.Theme.DARK, UiPalette.resolve(null, false));
        equal(UiPalette.Theme.DARK, UiPalette.resolve("mystery", true));
        equal(UiPalette.Theme.LIGHT, UiPalette.resolve("light", true));
        equal(UiPalette.Theme.DARK, UiPalette.resolve("system", true));
        equal(UiPalette.Theme.LIGHT, UiPalette.resolve("system", false));

        UiPalette dark = new UiPalette(UiPalette.Theme.DARK);
        UiPalette light = new UiPalette(UiPalette.Theme.LIGHT);
        equal(UiPalette.BLACK, dark.paper());
        equal(UiPalette.WHITE, dark.ink());
        equal(UiPalette.WHITE, light.paper());
        equal(UiPalette.BLACK, light.ink());
        equal(UiPalette.STROKE, dark.stroke());
        equal(UiPalette.STROKE, light.stroke());
        equal(UiPalette.ERROR_DARK, dark.error());
        equal(UiPalette.ERROR_LIGHT, light.error());
        equal(UiPalette.OK_DARK, dark.ok());
        equal(UiPalette.OK_LIGHT, light.ok());

        for (UiPalette palette : new UiPalette[]{dark, light}) {
            check(UiPalette.contrast(palette.ink(), palette.paper()) >= UiPalette.MIN_TEXT_CONTRAST,
                    "ink on paper " + palette.theme);
            check(UiPalette.contrast(palette.label(), palette.paper()) >= UiPalette.MIN_TEXT_CONTRAST,
                    "label on paper " + palette.theme);
            check(UiPalette.contrast(palette.error(), palette.paper()) >= UiPalette.MIN_TEXT_CONTRAST,
                    "error on paper " + palette.theme);
            check(UiPalette.contrast(palette.ok(), palette.paper()) >= UiPalette.MIN_TEXT_CONTRAST,
                    "ok on paper " + palette.theme);
            check(UiPalette.contrast(palette.stroke(), palette.paper()) >= UiPalette.MIN_STROKE_CONTRAST,
                    "stroke on paper " + palette.theme);
        }
        check(UiPalette.contrast(UiPalette.ERROR_DARK, UiPalette.BLACK) >= 4.5, "suggested red");
        check(UiPalette.contrast(UiPalette.OK_DARK, UiPalette.BLACK) >= 4.5, "suggested green");

        equal(UiPalette.Tone.ERROR, UiPalette.tone("Failed"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Garbled — Retry"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Stuck — Retry"));
        equal(UiPalette.Tone.PAUSED, UiPalette.tone("Paused — will continue when the Mac is back"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("USB cable disconnected · Waiting for the PC"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Not connected"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("validator rejected the answer"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("stream_error"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("This model could not start."));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Could not finish on this phone. Try again."));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Could not finish on the PC. Try again."));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Stopped early. Here is what it wrote."));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Stopped early. Here is what it sent."));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Stopped"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Phone unavailable"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Not enough free memory for this model right now."));
        equal(UiPalette.Tone.PAUSED, UiPalette.tone("Paused — plug the cable back in"));
        // A planned pause is never red: ink text, inverted chip, full-ink wall.
        equal(UiPalette.Tone.PAUSED, UiPalette.tone("Paused"));
        equal(UiPalette.Tone.PAUSED, UiPalette.tone("Paused — will continue when the MacBook is back"));
        for (UiPalette.Theme theme : UiPalette.Theme.values()) {
            UiPalette p = new UiPalette(theme);
            equal(p.ink(), p.colorForTone(UiPalette.Tone.PAUSED));
            equal(p.ink(), p.cardStroke(UiPalette.Tone.PAUSED));
            check(!UiPalette.CHROMATIC.contains(p.colorForTone(UiPalette.Tone.PAUSED)), "pause is not a colour");
        }
        check(!ErrorCopy.errorLine("Paused — plug the cable back in"), "pause is not an error line");
        equal(UiPalette.Tone.PAUSED, UiPalette.tone("MacBook · Paused"));
        equal(UiPalette.Tone.NEUTRAL, UiPalette.tone("Unpaused"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Paused — stuck"));
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Paused — garbled"));
        check(ErrorCopy.errorLine("Stuck — paused although the cable is back"), "stuck stays an error line");
        // A stuck lane that mentions a pause is still an error.
        equal(UiPalette.Tone.ERROR, UiPalette.tone("Stuck — paused although the cable is back"));
        equal(UiPalette.Tone.OK, UiPalette.tone("Done · 7.9 s"));
        equal(UiPalette.Tone.OK, UiPalette.tone("DONE"));
        equal(UiPalette.Tone.OK, UiPalette.tone("Ready"));
        equal(UiPalette.Tone.OK, UiPalette.tone("Connected"));
        equal(UiPalette.Tone.OK, UiPalette.tone("All lanes finished"));
        equal(UiPalette.Tone.OK, UiPalette.tone("Phone finished first by 3.2 s"));
        equal(UiPalette.Tone.OK, UiPalette.tone("PC and Phone finished together"));
        equal(UiPalette.Tone.OK, UiPalette.tone("PC finished first by 49.9 s · includes pause"));
        equal(UiPalette.Tone.NEUTRAL, UiPalette.tone("Getting the PC GPU ready…"));
        equal(UiPalette.Tone.NEUTRAL, UiPalette.tone("Streaming…"));
        equal(UiPalette.Tone.NEUTRAL, UiPalette.tone("Retry"));
        equal(UiPalette.Tone.ERROR, UiPalette.toneFromStatus("FAILED", false));
        equal(UiPalette.Tone.ERROR, UiPalette.toneFromStatus("DONE", true));
        equal(UiPalette.Tone.OK, UiPalette.toneFromStatus("DONE", false));
        check(UiPalette.retryAppliesToError(UiPalette.Tone.ERROR));
        check(!UiPalette.retryAppliesToError(UiPalette.Tone.OK));
        equal(UiPalette.ERROR_DARK, dark.cardStroke(UiPalette.Tone.ERROR));
        equal(UiPalette.STROKE, dark.cardStroke(UiPalette.Tone.OK));
        equal(UiPalette.ERROR_DARK, dark.colorForTone(UiPalette.Tone.ERROR));
        equal(UiPalette.OK_DARK, dark.colorForTone(UiPalette.Tone.OK));
        equal(UiPalette.WHITE, dark.colorForTone(UiPalette.Tone.NEUTRAL));
        System.out.println("UiPaletteTest: OK");
    }

    private static void check(boolean value) { check(value, "check"); }
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected " + expected + ", got " + actual);
        }
    }
}

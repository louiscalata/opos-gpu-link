package os.opos.launcher;

/**
 * The link line under the masthead and the cable-out banner (redesign Track 1 mockups).
 * Host-testable; no Android types. The line only claims a cable connection when Android
 * reports the USB cable in and the computer link is connected. Green is for that connected
 * line only; a planned cable pull is a pause, shown as the inverted ink banner, never red.
 */
final class LinkBanner {
    static final String BODY = "Plug the cable back in and it carries on from the same word.";

    private LinkBanner() {}

    /** "CONNECTED · MacBook over USB-C", or "" when the cable or the link is not confirmed. */
    static String line(Boolean cableConnected, boolean linkConnected, String noun) {
        if (!Boolean.TRUE.equals(cableConnected) || !linkConnected) return "";
        return "CONNECTED · " + ComputerWords.title(noun) + " over USB-C";
    }

    /** The banner shows only when the cable is out and a computer answer is on screen. */
    static boolean showBanner(Boolean cableConnected, boolean computerWorkVisible) {
        return Boolean.FALSE.equals(cableConnected) && computerWorkVisible;
    }

    /** "CABLE OUT · MacBook paused, nothing lost". */
    static String title(String noun) {
        return "CABLE OUT · " + ComputerWords.title(noun) + " paused, nothing lost";
    }

    /** For TalkBack, one sentence. */
    static String description(String noun) {
        return "Cable out. " + ComputerWords.title(noun) + " answer paused, nothing lost. " + BODY;
    }
}

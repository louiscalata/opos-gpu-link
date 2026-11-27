package os.opos.launcher;

public final class LinkBannerTest {
    private static int checks;

    public static void main(String[] args) {
        equal("CONNECTED · MacBook over USB-C", LinkBanner.line(true, true, "MacBook"));
        equal("CONNECTED · Mac over USB-C", LinkBanner.line(true, true, "Mac"));
        equal("CONNECTED · PC over USB-C", LinkBanner.line(true, true, "PC"));
        equal("CONNECTED · Computer over USB-C", LinkBanner.line(true, true, "computer"));
        // Never claim a cable link that is not confirmed.
        equal("", LinkBanner.line(true, false, "MacBook"));
        equal("", LinkBanner.line(false, true, "MacBook"));
        equal("", LinkBanner.line(null, true, "MacBook"));

        truth(LinkBanner.showBanner(false, true));
        truth(!LinkBanner.showBanner(false, false));
        truth(!LinkBanner.showBanner(true, true));
        truth(!LinkBanner.showBanner(null, true));

        equal("CABLE OUT · MacBook paused, nothing lost", LinkBanner.title("MacBook"));
        equal("CABLE OUT · PC paused, nothing lost", LinkBanner.title("PC"));
        truth(!LinkBanner.title("MacBook").contains("PC"));
        truth(LinkBanner.description("MacBook").startsWith("Cable out. MacBook answer paused"));
        truth(LinkBanner.description("MacBook").endsWith(LinkBanner.BODY));
        System.out.println("LinkBannerTest OK (" + checks + " checks)");
    }

    private static void equal(String expected, String actual) {
        checks++;
        if (!expected.equals(actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }

    private static void truth(boolean value) {
        checks++;
        if (!value) throw new AssertionError("check " + checks);
    }
}

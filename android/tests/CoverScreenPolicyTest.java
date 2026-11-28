package os.opos.launcher;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

public final class CoverScreenPolicyTest {
    private static final List<String> ORDER =
            Arrays.asList("phone", "gpu", "m1", "m2", "m3", "m4", "g1", "g2", "g3");

    public static void main(String[] args) {
        mode();
        priorities();
        selection();
        stability();
        labels();
        sizes();
        System.out.println("CoverScreenPolicyTest: OK");
    }

    private static void mode() {
        // Flip 6 cover: 748x720 px at 320 dpi.
        eq(CoverScreenPolicy.Mode.COVER, CoverScreenPolicy.select(374, 360, 1));
        eq(CoverScreenPolicy.Mode.COVER, CoverScreenPolicy.select(374, 360, 0));
        eq(CoverScreenPolicy.Mode.COVER, CoverScreenPolicy.select(360, 374, 1));
        // Flip 6 inner: 1080x2640 px at 480 dpi, portrait 360x880 dp.
        eq(CoverScreenPolicy.Mode.FULL, CoverScreenPolicy.select(360, 880, 0));
        // The same inner screen rotated to 2640x1080 px stays wide, not compact or cover.
        eq(CoverScreenPolicy.Mode.WIDE, CoverScreenPolicy.select(880, 360, 0));
        check(!CoverScreenPolicy.cover(CoverScreenPolicy.select(880, 360, 0)));
        eq(CoverScreenPolicy.Mode.FULL, CoverScreenPolicy.select(1200, 800, 0));
        // Inner screen in a short split window: compact, never the cover layout.
        eq(CoverScreenPolicy.Mode.COMPACT, CoverScreenPolicy.select(360, 520, 0));
        eq(CoverScreenPolicy.Mode.COMPACT, CoverScreenPolicy.select(360, 440, 0));
        eq(CoverScreenPolicy.Mode.COVER, CoverScreenPolicy.select(400, 400, 0));
        eq(CoverScreenPolicy.Mode.COMPACT, CoverScreenPolicy.select(401, 400, 0));
        // Undefined sizes (0) never pick the cover.
        eq(CoverScreenPolicy.Mode.COMPACT, CoverScreenPolicy.select(0, 0, 0));
        eq(CoverScreenPolicy.Mode.COMPACT, CoverScreenPolicy.select(0, 0, 1));
        eq(CoverScreenPolicy.Mode.COMPACT, CoverScreenPolicy.select(300, 1000, 0));
        // A somewhat larger secondary display still counts, a big external monitor does not.
        eq(CoverScreenPolicy.Mode.COVER, CoverScreenPolicy.select(420, 560, 1));
        eq(CoverScreenPolicy.Mode.FULL, CoverScreenPolicy.select(960, 1200, 2));
        check(CoverScreenPolicy.cover(CoverScreenPolicy.Mode.COVER));
        check(!CoverScreenPolicy.cover(CoverScreenPolicy.Mode.COMPACT));
        check(CoverScreenPolicy.needsRecreate(CoverScreenPolicy.Mode.FULL, CoverScreenPolicy.Mode.COVER));
        check(!CoverScreenPolicy.needsRecreate(CoverScreenPolicy.Mode.COVER, CoverScreenPolicy.Mode.COVER));
    }

    private static void priorities() {
        for (String live : new String[]{"answering", "loading", "queued", "waiting"}) {
            eq(0, CoverScreenPolicy.priority(live));
        }
        eq(1, CoverScreenPolicy.priority("paused"));
        eq(2, CoverScreenPolicy.priority("failed"));
        eq(3, CoverScreenPolicy.priority("done"));
        eq(4, CoverScreenPolicy.priority(""));
        eq(4, CoverScreenPolicy.priority(null));
        eq(4, CoverScreenPolicy.priority("cancelled"));
    }

    private static void selection() {
        eq(1, CoverScreenPolicy.MAX_PANES);
        // Nothing asked yet: the first three in newspaper order, one phone and one computer guaranteed.
        eq(Arrays.asList("phone", "gpu", "m1"), CoverScreenPolicy.visiblePanes(
                ORDER, states(), new ArrayList<>(), 3));
        // Busy phone models would crowd out the computer pane; it still stays.
        Map<String, String> busy = states("phone", "answering", "m1", "answering",
                "m2", "answering", "m3", "answering", "gpu", "done");
        eq(Arrays.asList("phone", "gpu", "m1"), CoverScreenPolicy.visiblePanes(
                ORDER, busy, new ArrayList<>(), 3));
        // Cable pulled: three computer panes frozen, phone panes live. Best of each side plus one more.
        Map<String, String> pulled = states("phone", "answering", "m1", "answering",
                "gpu", "paused", "g1", "paused", "g2", "paused");
        eq(Arrays.asList("phone", "gpu", "m1"), CoverScreenPolicy.visiblePanes(
                ORDER, pulled, new ArrayList<>(), 3));
        // An extra computer lane that is live beats a finished lane for the third slot.
        Map<String, String> mix = states("phone", "done", "gpu", "done", "m1", "done",
                "g2", "answering");
        eq(Arrays.asList("phone", "gpu", "g2"), CoverScreenPolicy.visiblePanes(
                ORDER, mix, new ArrayList<>(), 3));
        // Only phone lanes exist: no computer pane to keep, three phone panes.
        eq(Arrays.asList("phone", "m1", "m2"), CoverScreenPolicy.visiblePanes(
                Arrays.asList("phone", "m1", "m2", "m3"), states("m2", "answering"),
                new ArrayList<>(), 3));
        // One cover card shows the most active answer from either device.
        eq(Arrays.asList("m2"), CoverScreenPolicy.visiblePanes(
                ORDER, states("m2", "answering"), new ArrayList<>(), 1));
        eq(Arrays.asList("gpu"), CoverScreenPolicy.visiblePanes(
                ORDER, states("phone", "done", "gpu", "answering"),
                new ArrayList<>(), CoverScreenPolicy.MAX_PANES));
        eq(Arrays.asList("gpu"), CoverScreenPolicy.visiblePanes(
                ORDER, states("phone", "answering", "gpu", "answering"),
                Arrays.asList("phone"), CoverScreenPolicy.MAX_PANES));
        eq(Arrays.asList("phone"), CoverScreenPolicy.visiblePanes(
                ORDER, states("phone", "answering", "gpu", "waiting"),
                Arrays.asList("phone"), CoverScreenPolicy.MAX_PANES));
        eq(Arrays.asList("phone", "gpu"), CoverScreenPolicy.visiblePanes(
                Arrays.asList("phone", "gpu"), states(), new ArrayList<>(), 3));
        try {
            CoverScreenPolicy.visiblePanes(ORDER, states(), new ArrayList<>(), 0);
            throw new AssertionError("max 0 accepted");
        } catch (IllegalArgumentException expected) {}
        eq(6, CoverScreenPolicy.hiddenCount(9, 3));
        eq(0, CoverScreenPolicy.hiddenCount(2, 3));
    }

    private static void stability() {
        // A pane already on screen keeps its slot over an equally active newcomer.
        Map<String, String> tie = states("phone", "answering", "m1", "answering", "m2", "answering",
                "gpu", "answering");
        List<String> shown = Arrays.asList("phone", "gpu", "m2");
        eq(shown, CoverScreenPolicy.visiblePanes(ORDER, tie, shown, 3));
        // A strictly more active newcomer does replace a done pane.
        Map<String, String> later = states("phone", "answering", "m2", "done", "gpu", "answering",
                "m3", "answering");
        eq(Arrays.asList("phone", "gpu", "m3"), CoverScreenPolicy.visiblePanes(
                ORDER, later, shown, 3));
        check(!CoverScreenPolicy.shouldRearrange(shown, shown, false));
        check(CoverScreenPolicy.shouldRearrange(shown, Arrays.asList("phone", "gpu", "m3"), false));
        check(!CoverScreenPolicy.shouldRearrange(shown, Arrays.asList("phone", "gpu", "m3"), true));
    }

    private static void labels() {
        eq("LIVE", CoverScreenPolicy.indicator("answering"));
        eq("WAITING", CoverScreenPolicy.indicator("queued"));
        eq("PAUSED", CoverScreenPolicy.indicator("paused"));
        eq("DONE", CoverScreenPolicy.indicator("done"));
        eq("FAILED", CoverScreenPolicy.indicator("failed"));
        eq("STOPPED", CoverScreenPolicy.indicator("cancelled"));
        eq("", CoverScreenPolicy.indicator(""));
        eq("", CoverScreenPolicy.indicator(null));
        eq("paused", CoverScreenPolicy.visibleState("Paused · plug the cable back in"));
        eq("answering", CoverScreenPolicy.visibleState("Streaming…"));
        eq("waiting", CoverScreenPolicy.visibleState("Checking…"));
        eq("", CoverScreenPolicy.visibleState("Showing the last answer"));
        eq("done", CoverScreenPolicy.visibleState("Done · 2.1 s"));
        eq("cancelled", CoverScreenPolicy.visibleState("Stopped"));
        eq("cancelled", CoverScreenPolicy.visibleState("Stopped · 1.2 s"));
        eq("failed", CoverScreenPolicy.visibleState("Could not finish. Try again."));
        eq("failed", CoverScreenPolicy.visibleState("Paused — stuck"));
        eq("", CoverScreenPolicy.visibleState("Ready"));
        eq("", CoverScreenPolicy.visibleState("Not connected"));
        eq("", CoverScreenPolicy.visibleState("Not ready"));
        check(CoverScreenPolicy.invertIndicator("paused"));
        check(!CoverScreenPolicy.invertIndicator("answering"));
        eq("Computer GPU · PAUSED", CoverScreenPolicy.kicker("g1", "paused"));
        eq("PHONE · LIVE", CoverScreenPolicy.kicker("m1", "answering"));
        eq("Computer GPU", CoverScreenPolicy.kicker("gpu", ""));
        eq("", CoverScreenPolicy.moreLabel(0));
        eq("", CoverScreenPolicy.moreLabel(-1));
        eq("+1 more model · open the phone", CoverScreenPolicy.moreLabel(1));
        eq("+6 more models · open the phone", CoverScreenPolicy.moreLabel(6));
        check(!CoverScreenPolicy.userBusy(false, false, 10_000, 5_000));
        check(CoverScreenPolicy.userBusy(true, false, 10_000, 0));
        check(CoverScreenPolicy.userBusy(false, true, 10_000, 0));
        check(CoverScreenPolicy.userBusy(false, false, 6_999, 5_000));
        check(!CoverScreenPolicy.userBusy(false, false, 8_000, 5_000));
    }

    private static void sizes() {
        eq(40, CoverScreenPolicy.mastheadDp(false));
        eq(0, CoverScreenPolicy.mastheadDp(true));
        eq(52, CoverScreenPolicy.composerRowDp(false));
        eq(48, CoverScreenPolicy.composerRowDp(true));
        // 360 dp cover, 80 dp of sticky chrome: 360-80-40-52=188, minus 8 gap = 180.
        eq(80, CoverScreenPolicy.STICKY_CHROME_DP);
        eq(180, CoverScreenPolicy.paneHeightDp(360, CoverScreenPolicy.STICKY_CHROME_DP, 3));
        eq(188, CoverScreenPolicy.paneHeightDp(360, CoverScreenPolicy.STICKY_CHROME_DP, 1));
        // The page is wider than it is tall on the cover, but a pane never exceeds the viewport.
        check(CoverScreenPolicy.paneHeightDp(360, CoverScreenPolicy.STICKY_CHROME_DP, 3) < 360);
        // Very short window never goes below the minimum, tall window never above the maximum.
        eq(150, CoverScreenPolicy.paneHeightDp(200, 56, 3));
        eq(230, CoverScreenPolicy.paneHeightDp(700, 56, 3));
        // The keyboard row matches the compact layout's touch target size.
        check(CoverScreenPolicy.MASTHEAD_DP < CoverLayoutPolicy.MASTHEAD_DP);
        check(CoverScreenPolicy.COMPOSER_ROW_DP < CoverLayoutPolicy.COMPOSER_ROW_DP);
        check(CoverScreenPolicy.KEYBOARD_COMPOSER_ROW_DP
                == CoverLayoutPolicy.KEYBOARD_COMPOSER_ROW_DP);
        eq(32, CoverScreenPolicy.keepHeadlineVisible(120, 32, true, true));
        eq(10, CoverScreenPolicy.keepHeadlineVisible(10, 32, true, true));
        eq(0, CoverScreenPolicy.keepHeadlineVisible(0, 32, true, true));
        eq(120, CoverScreenPolicy.keepHeadlineVisible(120, 32, false, true));
        eq(120, CoverScreenPolicy.keepHeadlineVisible(120, 32, true, false));
        eq(0, CoverScreenPolicy.keepHeadlineVisible(-4, 32, true, true));
    }

    private static Map<String, String> states(String... pairs) {
        Map<String, String> result = new HashMap<>();
        for (int i = 0; i < pairs.length; i += 2) result.put(pairs[i], pairs[i + 1]);
        return result;
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void eq(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

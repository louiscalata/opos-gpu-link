package os.opos.launcher;

import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Host-testable decisions for the Galaxy Z Flip cover screen (748x720 px at 320 dpi, about
 * 374x360 dp). Nothing here touches Android classes.
 */
final class CoverScreenPolicy {
    enum Mode { FULL, COMPACT, COVER }

    /** The cover shows at most this many answer panes; the rest are summarised as "+N more". */
    static final int MAX_PANES = 3;
    static final int MASTHEAD_DP = 40;
    static final int COMPOSER_ROW_DP = 52;
    static final int KEYBOARD_COMPOSER_ROW_DP = 48;
    static final int MIN_PANE_DP = 150;
    static final int MAX_PANE_DP = 230;
    static final int SUMMARY_DP = 180;
    /** Status bar, connection line and lane-status line above the results (estimate, not measured). */
    static final int STICKY_CHROME_DP = 80;
    static final int QUESTION_SP = 21;
    static final int BODY_SP = 15;
    static final int MASTHEAD_SP = 24;

    private CoverScreenPolicy() {}

    /**
     * Cover on a small non-default display (at most 600 dp on both sides), or on the default display
     * when both sides are at most 400 dp. Undefined (zero) sizes never select the cover. Compact for
     * other narrow or short windows, full otherwise.
     */
    static Mode select(int widthDp, int heightDp, int displayId) {
        if (widthDp > 0 && heightDp > 0) {
            int longSide = Math.max(widthDp, heightDp);
            // Flex Window is display 1 on the Flip 6. On the default display only a window that is
            // small on both sides (the cover is 374x360 dp) counts, so an inner-screen split-screen
            // half (for example 360x440 dp) stays on the compact page.
            if (displayId != 0 && longSide <= 600) return Mode.COVER;
            if (displayId == 0 && widthDp <= 400 && heightDp <= 400) return Mode.COVER;
        }
        return NewspaperLayoutDecision.compact(widthDp, heightDp) ? Mode.COMPACT : Mode.FULL;
    }

    static boolean cover(Mode mode) {
        return mode == Mode.COVER;
    }

    /** A configChanges callback only rebuilds the page when the layout family really changes. */
    static boolean needsRecreate(Mode applied, Mode now) {
        return applied != now;
    }

    /** Smaller values are more important. Live work first, then frozen, failed, done, idle. */
    static int priority(String state) {
        if (state == null) return 4;
        switch (state) {
            case "answering": case "loading": case "queued": case "waiting": return 0;
            case "paused": return 1;
            case "failed": return 2;
            case "done": return 3;
            default: return 4;
        }
    }

    /**
     * Picks up to {@code max} panes in their original newspaper order. The best phone pane and the
     * best PC pane are always kept (the demo is about the two sides, so a frozen PC pane must not
     * disappear behind busier phone panes); remaining slots go to the most active panes. A pane that
     * is already visible wins ties so the page does not reshuffle under the reader.
     */
    static List<String> visiblePanes(List<String> order, Map<String, String> states,
                                     List<String> current, int max) {
        if (max < 1) throw new IllegalArgumentException("max must be at least 1");
        List<String> ranked = new ArrayList<>(order);
        ranked.sort(Comparator
                .comparingInt((String pane) -> priority(states.get(pane)))
                .thenComparingInt(pane -> current.contains(pane) ? 0 : 1)
                .thenComparingInt(order::indexOf));
        List<String> chosen = new ArrayList<>();
        for (boolean pc : new boolean[]{false, true}) {
            for (String pane : ranked) {
                if (PaneKeys.pc(pane) == pc) {
                    if (chosen.size() < max) chosen.add(pane);
                    break;
                }
            }
        }
        for (String pane : ranked) {
            if (chosen.size() >= max) break;
            if (!chosen.contains(pane)) chosen.add(pane);
        }
        List<String> result = new ArrayList<>();
        for (String pane : order) if (chosen.contains(pane)) result.add(pane);
        return result;
    }

    static final long INTERACTION_GRACE_MS = 3000;

    /** Busy while a finger is down, an article dialog is open, or for a grace period after scrolling. */
    static boolean userBusy(boolean touching, boolean dialogOpen, long nowMs, long lastInteractionMs) {
        return touching || dialogOpen || nowMs - lastInteractionMs < INTERACTION_GRACE_MS;
    }

    /** Re-arranging while a reader holds or scrolls a pane would yank the text away. */
    static boolean shouldRearrange(List<String> shown, List<String> wanted, boolean userBusy) {
        return !userBusy && !shown.equals(wanted);
    }

    static int hiddenCount(int totalPanes, int shownPanes) {
        return Math.max(0, totalPanes - shownPanes);
    }

    static String moreLabel(int hidden) {
        return hidden == 0 ? "" : "+" + hidden + " more models hidden";
    }

    /** Derive the cover badge from the words on the card, including offline and waiting paths. */
    static String visibleState(String words) {
        if (words == null) return "";
        String state = words.trim().toLowerCase(Locale.US);
        if (UiPalette.tone(state) == UiPalette.Tone.ERROR) return "failed";
        if (state.startsWith("paused")) return "paused";
        if (state.startsWith("streaming") || state.startsWith("answering")) return "answering";
        if (state.startsWith("done")) return "done";
        if (state.startsWith("stopped")) return "cancelled";
        if (state.startsWith("thinking") || state.startsWith("checking")
                || state.startsWith("waiting") || state.startsWith("loading")
                || state.startsWith("queued")) {
            return "waiting";
        }
        return "";
    }

    /** Short status word for the pane kicker. Empty means the pane has nothing to flag. */
    static String indicator(String state) {
        if (state == null) return "";
        switch (state) {
            case "answering": return "LIVE";
            case "loading": case "queued": case "waiting": return "WAITING";
            case "paused": return "PAUSED";
            case "done": return "DONE";
            case "failed": return "FAILED";
            case "cancelled": return "STOPPED";
            default: return "";
        }
    }

    /** Paused panes get an inverted chip (black on white) so a frozen pane reads at a glance. */
    static boolean invertIndicator(String state) {
        return "paused".equals(state);
    }

    static String kicker(String pane, String state) {
        String base = PaneKeys.kicker(pane);
        String word = indicator(state);
        return word.isEmpty() ? base : base + " · " + word;
    }

    static int composerRowDp(boolean keyboardVisible) {
        return keyboardVisible ? KEYBOARD_COMPOSER_ROW_DP : COMPOSER_ROW_DP;
    }

    static int mastheadDp(boolean keyboardVisible) {
        return keyboardVisible ? 0 : MASTHEAD_DP;
    }

    /**
     * On the cover, a page-anchor restore must not scroll the "You asked" headline
     * off the top of the short results viewport.
     */
    static int keepHeadlineVisible(int scrollY, int headlineTop, boolean cover, boolean headlineShown) {
        int y = Math.max(0, scrollY);
        if (!cover || !headlineShown) return y;
        return Math.min(y, Math.max(0, headlineTop));
    }

    /** Pane card height: share the room left above the composer, within the min and max limits. */
    static int paneHeightDp(int viewportDp, int stickyChromeDp, int shownPanes) {
        int room = viewportDp - stickyChromeDp - mastheadDp(false) - composerRowDp(false);
        int each = shownPanes <= 1 ? room : room - 8;
        return Math.max(MIN_PANE_DP, Math.min(MAX_PANE_DP, each));
    }
}

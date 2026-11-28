package os.opos.launcher;

import java.util.Arrays;
import java.util.List;

/**
 * Experimental black-and-white monospace views for the Design lab setting. Host-testable:
 * no Android imports. Every line of a frame is exactly {@code width} characters, so a
 * monospace TextView can redraw it in place without the layout jumping.
 */
final class DesignLab {
    static final String OFF = "off";
    static final String SCHEMATIC = "schematic";
    static final String BELTS = "belts";
    static final List<String> MODES = List.of(OFF, SCHEMATIC, BELTS);
    static final int MIN_WIDTH = 24;
    static final int MAX_WIDTH = 64;
    /** One animation step. Slow enough to read from a stage, cheap enough for a hot phone. */
    static final int TICK_MS = 160;
    private static final int GAP = 8;
    /** Below this many columns (the cover screen) the paused caption uses its short form. */
    static final String PAUSED_LONG = "Cable out · paused · resumes on plug-in";
    static final String PAUSED_SHORT = "Cable out · paused";
    static final int LONG_CAPTION_WIDTH = PAUSED_LONG.length();

    private DesignLab() {}

    /** UNPLUGGED: the cable is out with nothing to resume, so the cable is drawn cut. */
    enum Link { LIVE, PAUSED, IDLE, UNPLUGGED }

    /** A lane's belt: queued (empty), moving, paused (frozen), done (filled) or stopped (cut). */
    enum Belt { QUEUED, MOVING, PAUSED, DONE, STOPPED }

    /** Unknown or missing values fall back to Off, so the demo path stays the default. */
    static String parseMode(String value) {
        return value != null && MODES.contains(value) ? value : OFF;
    }

    /**
     * The cover screen has room for one small drawing, so any lab view other than Off shows
     * the link schematic there (belts need a line per lane). Off stays off.
     */
    static String coverMode(String mode) {
        return OFF.equals(parseMode(mode)) ? OFF : SCHEMATIC;
    }

    static String caption(String mode) {
        if (SCHEMATIC.equals(mode)) return "Connection diagram";
        if (BELTS.equals(mode)) return "Answer progress";
        return "Off (default)";
    }

    /** A pulled cable only pauses the link while the computer still has work open. */
    static Link link(Boolean cableConnected, boolean computerWorking) {
        boolean out = Boolean.FALSE.equals(cableConnected);
        if (!computerWorking) return out ? Link.UNPLUGGED : Link.IDLE;
        return out ? Link.PAUSED : Link.LIVE;
    }

    /**
     * Two boxes joined by a USB-C cable. LIVE moves tokens toward the phone each tick,
     * PAUSED cuts the cable and freezes, IDLE shows an empty cable. Five lines.
     */
    static String schematic(int tick, Link link, String computer, String phone, int width) {
        if (link == null) link = Link.IDLE;
        width = clamp(width);
        int left = (width - GAP) / 2;
        int right = width - GAP - left;
        String top = box('┌', '┐', left) + spaces(GAP) + box('┌', '┐', right);
        String middle = "│" + fit(computer, left - 2) + "│" + cable(tick, link) + "│"
                + fit(phone, right - 2) + "│";
        String bottom = box('└', '┘', left) + spaces(GAP) + box('└', '┘', right);
        String caption;
        switch (link) {
            case LIVE: caption = "USB-C · answer coming in"; break;
            case PAUSED:
                // Narrow (cover screen): the short form, never cut mid-word.
                caption = width >= LONG_CAPTION_WIDTH ? PAUSED_LONG : PAUSED_SHORT;
                break;
            case UNPLUGGED: caption = "Cable out"; break;
            default: caption = "USB-C · ready"; break;
        }
        String last = link == Link.PAUSED ? "‖ frozen" : "";
        return String.join("\n", top, middle, bottom, center(cut(caption, width), width),
                pad(last, width));
    }

    /** One lane as a conveyor: label, belt, word count. */
    static String belt(int tick, String label, int words, Belt state, int width) {
        if (state == null) state = Belt.QUEUED;
        width = clamp(width);
        String count = state == Belt.QUEUED && words <= 0 ? "—"
                : String.valueOf(Math.max(0, words)) + " w";
        int segment = width - 10 - 1 - 1 - 6;
        String belt;
        switch (state) {
            case DONE: belt = doneBelt(segment, words); break;
            case MOVING: belt = movingBelt(segment, tick); break;
            case PAUSED: belt = pausedBelt(segment); break;
            case STOPPED: belt = "╳" + repeat('─', segment - 1); break;
            default: belt = repeat('─', segment); break;
        }
        return fit(label, 10) + " " + belt + " " + padLeft(cut(count, 6), 6);
    }

    static String belts(int tick, List<Lane> lanes, int width) {
        if (lanes == null || lanes.isEmpty()) return fit("Ask a question to see progress.", clamp(width));
        StringBuilder out = new StringBuilder();
        for (Lane lane : lanes) {
            if (out.length() > 0) out.append('\n');
            out.append(belt(tick, lane.label, lane.words, lane.state, width));
        }
        return out.toString();
    }

    /** What a belt needs from a lane: its short label, words so far and its state. */
    static final class Lane {
        final String label;
        final int words;
        final Belt state;

        Lane(String label, int words, Belt state) {
            this.label = label == null ? "" : label;
            this.words = words;
            this.state = state == null ? Belt.QUEUED : state;
        }
    }

    /**
     * Maps the lane's on-screen state words to a belt. Fails closed to QUEUED: only words
     * the app already shows ("Streaming…", "Paused …", "Done …") move or fill a belt.
     */
    static Belt beltFor(String stateWords) {
        String state = stateWords == null ? "" : stateWords.trim();
        if (state.startsWith("Done")) return Belt.DONE;
        if (state.startsWith("Paused")) return Belt.PAUSED;
        if (state.startsWith("Streaming") || state.startsWith("Thinking")) return Belt.MOVING;
        if (state.startsWith("Stopped")) return Belt.STOPPED;
        if (ErrorCopy.errorLine(state)) return Belt.STOPPED;
        return Belt.QUEUED;
    }

    private static String cable(int tick, Link link) {
        if (link == Link.PAUSED || link == Link.UNPLUGGED) return "══╳  ╳══";
        char[] cells = repeat('═', GAP).toCharArray();
        if (link == Link.LIVE) {
            for (int i = Math.floorMod(tick, 3); i < GAP; i += 3) cells[i] = '■';
            cells[GAP - 1] = '▶';
        }
        return new String(cells);
    }

    private static String movingBelt(int length, int tick) {
        char[] cells = repeat('>', length).toCharArray();
        int shift = Math.floorMod(tick, 4);
        for (int i = shift; i < length; i += 4) cells[i] = '■';
        return new String(cells);
    }

    private static String pausedBelt(int length) {
        char[] cells = repeat('─', length).toCharArray();
        cells[0] = '‖';
        for (int i = 2; i < length; i += 4) cells[i] = '■';
        return new String(cells);
    }

    private static String doneBelt(int length, int words) {
        int fill = (int) Math.round(length * Math.min(Math.max(0, words), 400) / 400.0);
        if (words > 0 && fill == 0) fill = 1;
        return repeat('■', fill) + repeat('□', length - fill);
    }

    private static String box(char start, char end, int outer) {
        return start + repeat('─', outer - 2) + end;
    }

    private static String fit(String text, int width) {
        String flat = text == null ? "" : text.replace('\n', ' ').replace('\r', ' ').trim();
        return pad(cut(flat, width), width);
    }

    private static String cut(String text, int width) {
        if (text.length() <= width) return text;
        return width <= 0 ? "" : text.substring(0, width - 1) + '…';
    }

    private static String center(String text, int width) {
        int left = (width - text.length()) / 2;
        return pad(spaces(left) + text, width);
    }

    private static String pad(String text, int width) {
        return text + spaces(width - text.length());
    }

    private static String padLeft(String text, int width) {
        return spaces(width - text.length()) + text;
    }

    private static String spaces(int count) {
        return repeat(' ', count);
    }

    private static String repeat(char c, int count) {
        if (count <= 0) return "";
        char[] cells = new char[count];
        Arrays.fill(cells, c);
        return new String(cells);
    }

    private static int clamp(int width) {
        return Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, width));
    }
}

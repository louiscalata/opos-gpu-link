package os.opos.launcher;

import java.util.List;

public final class DesignLabTest {
    private static final String ALLOWED = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 \n\r\t.,:;!?()[]{}<>+-=*/_%&|\\'\"`~@#^$·─│┌┐└┘═▶■□╳‖—";

    public static void main(String[] args) {
        check(DesignLab.parseMode(null).equals(DesignLab.OFF));
        check(DesignLab.parseMode("x").equals(DesignLab.OFF));
        check(DesignLab.parseMode("schematic").equals(DesignLab.SCHEMATIC));
        check(DesignLab.parseMode("belts").equals(DesignLab.BELTS));

        equal("Off (default)", DesignLab.caption(DesignLab.OFF));
        equal("Link schematic", DesignLab.caption(DesignLab.SCHEMATIC));
        equal("Factory belts", DesignLab.caption(DesignLab.BELTS));

        check(DesignLab.link(Boolean.FALSE, true) == DesignLab.Link.PAUSED);
        check(DesignLab.link(Boolean.TRUE, true) == DesignLab.Link.LIVE);
        check(DesignLab.link(null, true) == DesignLab.Link.LIVE);
        check(DesignLab.link(Boolean.FALSE, false) == DesignLab.Link.UNPLUGGED);
        check(DesignLab.link(Boolean.TRUE, false) == DesignLab.Link.IDLE);
        check(DesignLab.link(null, false) == DesignLab.Link.IDLE);

        for (int width : new int[]{24, 40, 64}) {
            for (DesignLab.Link link : DesignLab.Link.values()) {
                String a = DesignLab.schematic(0, link, "Computer", "Phone", width);
                String b = DesignLab.schematic(1, link, "Computer", "Phone", width);
                String[] la = a.split("\n", -1), lb = b.split("\n", -1);
                check(la.length == 5 && lb.length == 5);
                for (String s : la) check(s.length() == width);
                for (String s : lb) check(s.length() == width);
                check(allowed(a) && allowed(b));
            }
        }

        String live0 = DesignLab.schematic(0, DesignLab.Link.LIVE, "Computer", "Phone", 40);
        String live1 = DesignLab.schematic(1, DesignLab.Link.LIVE, "Computer", "Phone", 40);
        check(!live0.equals(live1));

        String paused0 = DesignLab.schematic(0, DesignLab.Link.PAUSED, "Computer", "Phone", 40);
        String paused5 = DesignLab.schematic(5, DesignLab.Link.PAUSED, "Computer", "Phone", 40);
        equal(paused0, paused5);
        check(paused0.contains("╳"));
        check(allowed(paused0));

        String idle = DesignLab.schematic(0, DesignLab.Link.IDLE, "Computer", "Phone", 40);
        check(!idle.split("\n", -1)[1].contains("■"));
        check(allowed(idle));

        String trunc = DesignLab.schematic(0, DesignLab.Link.LIVE, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "ABCDEFGHIJKLMNOPQRSTUVWXYZ", 24);
        check(trunc.contains("…"));
        check(allowed(trunc));

        String beltA = DesignLab.belt(0, "LabelLongerThanTen", 7, DesignLab.Belt.MOVING, 24);
        String beltB = DesignLab.belt(1, "LabelLongerThanTen", 7, DesignLab.Belt.MOVING, 24);
        check(beltA.length() == 24);
        check(!beltA.equals(beltB));
        check(allowed(beltA) && allowed(beltB));

        String stopped0 = DesignLab.belt(0, "Stop", 3, DesignLab.Belt.PAUSED, 24);
        String stopped5 = DesignLab.belt(5, "Stop", 3, DesignLab.Belt.PAUSED, 24);
        equal(stopped0, stopped5);
        check(stopped0.substring(11).startsWith("‖"));
        check(allowed(stopped0));

        String done = DesignLab.belt(0, "Done", 400, DesignLab.Belt.DONE, 24);
        check(done.length() == 24);
        check(!done.contains(">"));
        check(allowed(done));

        List<DesignLab.Lane> lanes = List.of(
                new DesignLab.Lane("A", 1, DesignLab.Belt.MOVING),
                new DesignLab.Lane("B", 2, DesignLab.Belt.PAUSED),
                new DesignLab.Lane("C", 400, DesignLab.Belt.DONE)
        );
        String belts = DesignLab.belts(3, lanes, 40);
        String[] lines = belts.split("\n", -1);
        check(lines.length == lanes.size());
        for (String s : lines) {
            check(s.length() == 40);
            check(allowed(s));
        }

        // The paused frame names the pause in words, never colour alone.
        check(paused0.contains("paused"));
        check(live0.split("\n", -1)[1].contains("▶"));
        equal("72 w", DesignLab.belt(0, "MacBook", 72, DesignLab.Belt.DONE, 40).substring(34).trim());
        // A queued lane is an empty belt, not a stopped one, and shows no count yet.
        String queued = DesignLab.belt(2, "Nemotron", 0, DesignLab.Belt.QUEUED, 40);
        equal(queued, DesignLab.belt(7, "Nemotron", 0, DesignLab.Belt.QUEUED, 40));
        check(!queued.contains("■") && !queued.contains("‖"));
        check(queued.endsWith("—"));
        check(DesignLab.beltFor("Done · 28.4 s") == DesignLab.Belt.DONE);
        check(DesignLab.beltFor("Paused — will continue when the MacBook is back") == DesignLab.Belt.PAUSED);
        check(DesignLab.beltFor("Streaming…") == DesignLab.Belt.MOVING);
        check(DesignLab.beltFor("Waiting for its turn…") == DesignLab.Belt.QUEUED);
        check(DesignLab.beltFor("Stopped") == DesignLab.Belt.STOPPED);
        check(DesignLab.belt(0, "Phone", 12, DesignLab.Belt.STOPPED, 40).substring(11).startsWith("╳"));
        check(DesignLab.beltFor(null) == DesignLab.Belt.QUEUED);
        // Panel cases: nulls, an idle unplugged cable, short finished answers, newlines.
        check(DesignLab.link(Boolean.FALSE, false) == DesignLab.Link.UNPLUGGED);
        String unplugged = DesignLab.schematic(0, DesignLab.Link.UNPLUGGED, "MacBook", "This phone", 40);
        check(unplugged.contains("╳") && unplugged.contains("Cable out"));
        equal(DesignLab.schematic(0, DesignLab.Link.IDLE, "MacBook", "Phone", 40),
                DesignLab.schematic(0, null, "MacBook", "Phone", 40));
        check(DesignLab.belt(0, "Nemotron", 0, null, 40).endsWith("—"));
        check(DesignLab.belt(0, "Phone", 5, DesignLab.Belt.DONE, 24).contains("■"));
        for (String line : DesignLab.schematic(0, DesignLab.Link.LIVE, "Mac\nBook", "Phone", 40).split("\n", -1)) {
            check(line.length() == 40);
        }
        equal(40, DesignLab.belts(0, List.of(), 40).length());
        equal(24, DesignLab.belts(0, List.of(), 24).length());
        System.out.println("DesignLabTest: OK");
    }

    private static boolean allowed(String s) {
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            if (c == '…' || ALLOWED.indexOf(c) >= 0) continue;
            return false;
        }
        return true;
    }

    private static void check(boolean v) {
        if (!v) throw new AssertionError();
    }

    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected=" + expected + ", actual=" + actual);
        }
    }
}

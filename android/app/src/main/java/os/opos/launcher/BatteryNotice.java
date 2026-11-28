package os.opos.launcher;

/** A quiet charge reminder when the phone battery is low and unplugged. */
final class BatteryNotice {
    static final int LOW_PERCENT = 15;

    private BatteryNotice() {}

    static boolean show(int level, int scale, boolean charging) {
        return !charging && level >= 0 && scale > 0
                && (long) level * 100 <= (long) LOW_PERCENT * scale;
    }
}

package os.opos.launcher;

public final class BatteryNoticeTest {
    public static void main(String[] args) {
        check(BatteryNotice.show(15, 100, false));
        check(BatteryNotice.show(7, 50, false));
        check(!BatteryNotice.show(16, 100, false));
        check(!BatteryNotice.show(10, 100, true));
        check(!BatteryNotice.show(-1, 100, false));
        check(!BatteryNotice.show(10, 0, false));
        System.out.println("BatteryNoticeTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
}

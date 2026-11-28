package os.opos.launcher;

public final class DeviceLayoutPolicyTest {
    public static void main(String[] args) {
        eq(1, DeviceLayoutPolicy.columns(360, false, 4));
        eq(1, DeviceLayoutPolicy.columns(374, true, 4));
        eq(1, DeviceLayoutPolicy.columns(880, false, 1));
        eq(2, DeviceLayoutPolicy.columns(600, false, 2));
        eq(2, DeviceLayoutPolicy.columns(880, false, 4));
        eq(DeviceLayoutPolicy.Side.PHONE, DeviceLayoutPolicy.side("phone", ""));
        eq(DeviceLayoutPolicy.Side.PHONE, DeviceLayoutPolicy.side("m1", "phone"));
        eq(DeviceLayoutPolicy.Side.PHONE, DeviceLayoutPolicy.side("m4", ""));
        eq(DeviceLayoutPolicy.Side.COMPUTER, DeviceLayoutPolicy.side("gpu", ""));
        eq(DeviceLayoutPolicy.Side.COMPUTER, DeviceLayoutPolicy.side("g1", "pc"));
        eq(DeviceLayoutPolicy.Side.UNKNOWN, DeviceLayoutPolicy.side("other", ""));
        eq(DeviceLayoutPolicy.Side.PHONE,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.PHONE, 0, 1));
        eq(DeviceLayoutPolicy.Side.COMPUTER,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.COMPUTER, 1, 0));
        eq(DeviceLayoutPolicy.Side.COMPUTER,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.PHONE, 1, 0));
        eq(DeviceLayoutPolicy.Side.COMPUTER,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.PHONE, 3, 1));
        eq(DeviceLayoutPolicy.Side.COMPUTER,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.PHONE, 2, 1));
        eq(DeviceLayoutPolicy.LinkState.CABLE_OUT,
                DeviceLayoutPolicy.linkState(false, true, false, true));
        eq(DeviceLayoutPolicy.LinkState.PAUSED,
                DeviceLayoutPolicy.linkState(true, false, true, false));
        eq(DeviceLayoutPolicy.LinkState.ERROR,
                DeviceLayoutPolicy.linkState(true, false, false, true));
        eq(DeviceLayoutPolicy.LinkState.ERROR,
                DeviceLayoutPolicy.linkState(true, false, true, true));
        eq(DeviceLayoutPolicy.LinkState.CONNECTED,
                DeviceLayoutPolicy.linkState(true, true, false, false));
        eq(DeviceLayoutPolicy.LinkState.WAITING,
                DeviceLayoutPolicy.linkState(null, true, false, false));
        eq("Phone connected to MacBook Pro by USB-C",
                DeviceLayoutPolicy.description("MacBook Pro", DeviceLayoutPolicy.LinkState.CONNECTED));
        System.out.println("DeviceLayoutPolicyTest: OK");
    }

    private static void eq(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

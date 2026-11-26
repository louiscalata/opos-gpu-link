package os.opos.launcher;

import java.util.Map;

public final class ForgetActionTest {
    public static void main(String[] args) {
        Map<String, String> bound = ForgetAction.body("0123456789abcdef");
        equal(2, bound.size());
        equal("forget", bound.get("action"));
        equal("0123456789abcdef", bound.get("expect"));
        Map<String, String> legacy = ForgetAction.body("");
        equal(1, legacy.size());
        equal("forget", legacy.get("action"));
        check(!legacy.containsKey("expect"));
        check(!ForgetAction.body("unavailable").containsKey("expect"));
        check(ForgetAction.canConfirm("Stage PC", "0123456789abcdef",
                "Stage PC", "0123456789abcdef"));
        check(!ForgetAction.canConfirm("Stage PC", "0123456789abcdef",
                "Stage PC", "fedcba9876543210"));
        check(!ForgetAction.canConfirm("Stage PC", "0123456789abcdef",
                null, ""));
        check(ForgetAction.canConfirm("Legacy PC", "", "Legacy PC", ""));
        check(!ForgetAction.canConfirm("Legacy PC", "", "Other PC", ""));
        check(!ForgetAction.canConfirm("Legacy PC", "", "Legacy PC",
                "0123456789abcdef"));
        System.out.println("ForgetActionTest: OK");
    }
    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

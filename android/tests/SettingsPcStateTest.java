package os.opos.launcher;

/** Host checks for Settings rows as a PC is forgotten and replaced. */
public final class SettingsPcStateTest {
    public static void main(String[] args) {
        SettingsPcState paired = SettingsPcState.from(true, true, false, false,
                " Stage PC ", "0123456789abcdef",
                SettingsPcState.Connection.CONNECTED, true);
        equal("Stage PC", paired.label);
        equal("0123456789abcdef", paired.fingerprint);
        equal(SettingsPcState.Connection.CONNECTED, paired.connection);
        equal(SettingsPcState.Pairing.SAVED, paired.pairing);
        check(paired.canForget);

        SettingsPcState forgotten = SettingsPcState.from(true, false, false, false,
                "Stage PC", "0123456789abcdef",
                SettingsPcState.Connection.CONNECTED, true);
        equal("", forgotten.label);
        equal("", forgotten.fingerprint);
        equal(SettingsPcState.Connection.DISCONNECTED, forgotten.connection);
        equal(SettingsPcState.Pairing.NONE, forgotten.pairing);
        check(!forgotten.canForget);

        SettingsPcState pending = SettingsPcState.from(true, false, true, false,
                "Travelling PC", "", SettingsPcState.Connection.PAIRING, true);
        equal("", pending.label);
        equal(SettingsPcState.Connection.PAIRING, pending.connection);
        equal(SettingsPcState.Pairing.REQUESTED, pending.pairing);
        check(!pending.canForget);

        SettingsPcState replacement = SettingsPcState.from(true, true, false, false,
                "Travelling PC", "fedcba9876543210",
                SettingsPcState.Connection.CONNECTED, true);
        equal("Travelling PC", replacement.label);
        equal("fedcba9876543210", replacement.fingerprint);
        equal(SettingsPcState.Pairing.SAVED, replacement.pairing);
        check(replacement.canForget);

        SettingsPcState offline = SettingsPcState.from(true, true, false, false,
                "Stage PC", "0123456789abcdef",
                SettingsPcState.Connection.UNKNOWN, false);
        check(!offline.canForget);
        equal(SettingsPcState.Pairing.SAVED, offline.pairing);
        System.out.println("SettingsPcStateTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

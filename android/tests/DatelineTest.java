package os.opos.launcher;

import java.time.LocalDate;

public final class DatelineTest {
    public static void main(String[] args) {
        equal("WED 25 NOV 2026 \u00b7 PHONE + PC GPU EDITION",
                Dateline.format(LocalDate.of(2026, 11, 25)));
        equal("FRI 2 JAN 2026 \u00b7 PHONE + PC GPU EDITION",
                Dateline.format(LocalDate.of(2026, 1, 2)));
        System.out.println("DatelineTest: OK");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

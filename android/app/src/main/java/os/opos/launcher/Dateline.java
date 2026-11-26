package os.opos.launcher;

import java.time.LocalDate;
import java.time.format.DateTimeFormatter;
import java.util.Locale;

/** Edition date, derived from the device's local calendar day. */
final class Dateline {
    private static final DateTimeFormatter DATE =
            DateTimeFormatter.ofPattern("EEE d MMM yyyy", Locale.US);

    private Dateline() {}

    static String format(LocalDate date) {
        return DATE.format(date).toUpperCase(Locale.US)
                + ComputerWords.apply(" \u00b7 PHONE + PC GPU EDITION");
    }
}

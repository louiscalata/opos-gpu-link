package os.opos.launcher;

import java.nio.file.Files;
import java.nio.file.Path;

/** Keep green on success and live work, not on heat or the fastest line. */
public final class GreenRuleTest {
    public static void main(String[] args) throws Exception {
        for (UiPalette.Theme theme : UiPalette.Theme.values()) {
            UiPalette palette = new UiPalette(theme);
            for (int status = 0; status <= 6; status++) {
                String color = palette.colorForTone(HeatMeter.tone(status));
                check(!color.equals(palette.ok()), "heat status " + status + " is not success");
                check(color.equals(status >= 3 ? palette.error() : palette.ink()),
                        "heat status " + status + " uses the active palette");
            }
            check(palette.colorForTone(UiPalette.tone("Done")).equals(palette.ok()),
                    "Done keeps success green");
        }

        // MainActivity is Android-only, so host tests inspect the display wiring here.
        String activity = Files.readString(Path.of(
                "app/src/main/java/os/opos/launcher/MainActivity.java"));
        String tonight = between(activity, "private void fillTonightRows(",
                "List<TonightRows.Row> rows = TonightRows.parse(timing);");
        check(tonight.contains("tonightLeader.setTextColor(parseHex(palette.ink()));"),
                "fastest line uses ink");
        check(!tonight.contains("palette.ok()"), "fastest line never uses success green");
        check(activity.contains("heatMeter.setTextColor(parseHex(palette.colorForTone(HeatMeter.tone(status))));"),
                "heat meter uses its tested tone");
        String working = between(activity, "private void setWorkingText(",
                "/** Shows or hides one lane's working line;");
        check(working.contains("int green = parseHex(palette.ok());")
                        && working.contains("spans.dot = new AlphaColorSpan(green);"),
                "live working dot keeps success green");
        System.out.println("GreenRuleTest: OK");
    }

    private static String between(String source, String start, String end) {
        int from = source.indexOf(start);
        int to = source.indexOf(end, from);
        if (from < 0 || to < 0) throw new AssertionError("fastest line wiring missing");
        return source.substring(from, to);
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }
}

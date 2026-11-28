package os.opos.launcher;

import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/** Keeps raw off-grid dp values out of layout spacing. */
public final class SpacingAuditTest {
    private static final Path JAVA = Path.of("app/src/main/java/os/opos/launcher");
    private static final Path LAYOUT = Path.of("app/src/main/res/layout");
    private static final Pattern DP_CALL = Pattern.compile("\\bdp\\(([^)]*)\\)");
    private static final Pattern NUMBER = Pattern.compile("\\b\\d+\\b");
    private static final Pattern XML_SPACING = Pattern.compile(
            "android:(?:layout_margin\\w*|padding\\w*)=\"(\\d+)dp\"");

    public static void main(String[] args) throws IOException {
        checkToken("space_xs", Space.XS, 4);
        checkToken("space_s", Space.S, 8);
        checkToken("space_m", Space.M, 12);
        checkToken("space_l", Space.L, 16);
        checkToken("space_xl", Space.XL, 24);
        equal(6, LaneCardLayout.CARD_GAP_DP); // Documented card-gap exception.
        equal(Space.S, PairingPrompt.gapDp(true));

        List<String> hits = new ArrayList<>();
        try (DirectoryStream<Path> files = Files.newDirectoryStream(JAVA, "*.java")) {
            for (Path file : files) {
                if (file.getFileName().toString().equals("Space.java")) continue;
                String source = Files.readString(file);
                Matcher call = DP_CALL.matcher(source);
                while (call.find()) {
                    String argument = call.group(1);
                    // Scan plain literals and both arms of a conditional, including mixed
                    // forms such as coverMode ? 6 : Space.S. Other dp expressions are sizes.
                    if (!argument.matches("\\s*\\d+\\s*") && !argument.contains("?")) continue;
                    Matcher number = NUMBER.matcher(argument);
                    while (number.find()) {
                        int value = Integer.parseInt(number.group());
                        if (value % 4 != 0 && !nonSpacingException(source, call.start(), value)) {
                            hits.add(location(file, source, call.start()) + ": dp(" + argument.trim() + ")");
                        }
                    }
                }
            }
        }
        try (DirectoryStream<Path> files = Files.newDirectoryStream(LAYOUT, "*.xml")) {
            for (Path file : files) {
                String source = Files.readString(file);
                Matcher spacing = XML_SPACING.matcher(source);
                while (spacing.find()) {
                    int value = Integer.parseInt(spacing.group(1));
                    if (value % 4 != 0) {
                        hits.add(location(file, source, spacing.start()) + ": raw " + value + "dp spacing");
                    }
                }
            }
        }
        if (!hits.isEmpty()) throw new AssertionError("Off-grid dp literals: " + hits);
        System.out.println("SpacingAuditTest: OK");
    }

    private static void checkToken(String name, int actual, int expected) throws IOException {
        equal(expected, actual);
        String xml = Files.readString(Path.of("app/src/main/res/values/spacing.xml"));
        String declaration = "<dimen name=\"" + name + "\">" + expected + "dp</dimen>";
        if (!xml.contains(declaration)) throw new AssertionError("Missing spacing token: " + declaration);
    }

    private static boolean nonSpacingException(String source, int at, int value) {
        int start = source.lastIndexOf('\n', at) + 1;
        int end = source.indexOf('\n', at);
        String line = source.substring(start, end < 0 ? source.length() : end).trim();
        // Borders, a touch threshold, a corner radius and popup width are dimensions,
        // not spacing. Card-gap calls use LaneCardLayout.CARD_GAP_DP instead.
        return switch (value) {
            case 1 -> line.contains("setPadding(dp(1)")
                    || line.contains("MATCH_PARENT, dp(1)");
            case 2 -> line.contains("expandedTouchY) > dp(2)")
                    || line.contains("setStroke(highlight ? dp(2)")
                    || line.contains("setStroke(Math.max(2, dp(2))");
            case 10 -> line.contains("float radius = dp(10)");
            case 230 -> line.contains("new PopupWindow(list, dp(230)");
            default -> false;
        };
    }

    private static String location(Path file, String source, int at) {
        int line = 1;
        for (int i = 0; i < at; i++) if (source.charAt(i) == '\n') line++;
        return file + ":" + line;
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

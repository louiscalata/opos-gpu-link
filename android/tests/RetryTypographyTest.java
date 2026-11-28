package os.opos.launcher;

import java.nio.file.Files;
import java.nio.file.Path;

/** Guard the Retry action's body role and flexible height without an Android runtime. */
public final class RetryTypographyTest {
    public static void main(String[] args) throws Exception {
        TypeConfig.Role body = TypeConfig.body();
        equal("B5", body.id);
        equal(TypeConfig.FACE_TEXT_REGULAR, body.face);
        equal(17, body.size(false));
        equal(14, body.size(true));

        String typography = Files.readString(Path.of(
                "app/src/main/java/os/opos/launcher/Typography.java"));
        String retry = section(typography, "void retry(TextView text)", "void body(TextView text");
        require(retry, "choice.body()");
        require(retry, "role.size(cover)");
        require(retry, "apply(text, role, role.size(cover), false, role.face)");
        reject(retry, "choice.subheader()");

        String activity = Files.readString(Path.of(
                "app/src/main/java/os/opos/launcher/MainActivity.java"));
        String lane = section(activity, "private void addLaneRetryButton(",
                "/** Show Retry on a lane");
        require(lane, "typography.retry(button)");
        require(lane, "button.setSingleLine(false)");
        require(lane, "button.setEllipsize(null)");
        require(lane, "LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT");
        String outline = section(activity, "private Button outlineButton(",
                "private LinearLayout pageBar(");
        require(outline, "button.setMinHeight(dp(48))");
        String pageType = section(activity, "private void applyTypographyToPage()",
                "private void showSettings()");
        require(pageType, "for (Button laneRetry : laneRetryButtons.values()) typography.retry(laneRetry)");

        String layout = Files.readString(Path.of("app/src/main/res/layout/models.xml"));
        String pageRetry = button(layout, "retry");
        require(pageRetry, "android:layout_height=\"wrap_content\"");
        require(pageRetry, "android:minHeight=\"52dp\"");
        require(pageRetry, "android:text=\"@string/lane_retry\"");
        String reopen = button(layout, "reopen_pc");
        require(reopen, "android:layout_height=\"wrap_content\"");
        require(reopen, "android:minHeight=\"52dp\"");
        System.out.println("RetryTypographyTest: OK");
    }

    private static String button(String layout, String id) {
        return section(layout, "android:id=\"@+id/" + id + "\"", "/>");
    }

    private static String section(String source, String startText, String endText) {
        int start = source.indexOf(startText);
        int end = source.indexOf(endText, start);
        if (start < 0 || end < 0) throw new AssertionError("Missing " + startText);
        return source.substring(start, end);
    }

    private static void require(String text, String phrase) {
        if (!text.contains(phrase)) throw new AssertionError("Missing " + phrase);
    }

    private static void reject(String text, String phrase) {
        if (text.contains(phrase)) throw new AssertionError("Unexpected " + phrase);
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

package os.opos.launcher;

import java.nio.file.Files;
import java.nio.file.Path;

/** Host audit of transitions that cannot be run without Android views. */
public final class LiveSpeedWiringTest {
    public static void main(String[] args) throws Exception {
        String source = Files.readString(Path.of(
                "app/src/main/java/os/opos/launcher/MainActivity.java"));
        require(between(source, "private void showWaiting()", "private void showOffline("),
                "setLiveSpeed(pane, \"\")");
        String offline = between(source, "private void showOffline(", "private void showSnapshot(");
        if (count(offline, "setLiveSpeed(pane, \"\")") != 2) {
            throw new AssertionError("Both offline paths must clear speed");
        }
        require(between(source, "private void clearNewspaperContent()",
                "private boolean answerShown("), "setLiveSpeed(article, \"\")");
        String locked = between(source, "if (data.optBoolean(\"locked\")) {",
                "JSONObject phone = data.optJSONObject(\"phone\")");
        require(locked, "clearNewspaperContent()");
        require(between(source, "private void plainArticle(", "private void setWaitingLayout("),
                "setLiveSpeed(article, \"\")");
        require(between(source, "private void setLiveSpeed(", "private static void setVisibilityIfNeeded("),
                "speed.isEmpty() ? View.GONE : View.VISIBLE");
        String render = between(source, "private void renderPane(", "private String answerWords(");
        int state = render.indexOf("String stateWords =");
        int speed = render.indexOf("setLiveSpeed(article, LiveSpeedLabel.text(");
        if (state < 0 || speed < state) {
            throw new AssertionError("Speed must follow the state shown on the card");
        }
        System.out.println("LiveSpeedWiringTest: OK");
    }

    private static String between(String source, String start, String end) {
        int from = source.indexOf(start);
        int to = source.indexOf(end, from + start.length());
        if (from < 0 || to < 0) throw new AssertionError("Method boundary missing: " + start);
        return source.substring(from, to);
    }

    private static void require(String text, String phrase) {
        if (!text.contains(phrase)) throw new AssertionError("Missing " + phrase);
    }

    private static int count(String text, String phrase) {
        int result = 0;
        for (int at = text.indexOf(phrase); at >= 0; at = text.indexOf(phrase, at + phrase.length())) {
            result++;
        }
        return result;
    }
}

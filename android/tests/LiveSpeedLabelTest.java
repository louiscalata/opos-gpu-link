package os.opos.launcher;

public final class LiveSpeedLabelTest {
    public static void main(String[] args) {
        equal("17 tokens a second · this run", LiveSpeedLabel.text(17, "answering", true));
        equal("2.5 tokens a second · this run", LiveSpeedLabel.text(2.5, "answering", true));
        equal("", LiveSpeedLabel.text(17, "done", true));
        equal("", LiveSpeedLabel.text(17, "answering", false));
        equal("", LiveSpeedLabel.text(0, "answering", true));
        equal("", LiveSpeedLabel.text(-1, "answering", true));
        equal("", LiveSpeedLabel.text(Double.NaN, "answering", true));
        equal("", LiveSpeedLabel.text(Double.POSITIVE_INFINITY, "answering", true));
        equal("", LiveSpeedLabel.text("17", "answering", true));
        equal("", LiveSpeedLabel.text(null, "answering", true));
        equal("", LiveSpeedLabel.text(Long.MAX_VALUE, "answering", true));
        System.out.println("LiveSpeedLabelTest: OK");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

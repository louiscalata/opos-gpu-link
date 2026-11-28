package os.opos.launcher;

public final class SummaryPaintPolicyTest {
    public static void main(String[] args) {
        SummaryPaintPolicy.Paint shown = new SummaryPaintPolicy.Paint("Phone is answering", 1, 2, 17);
        check(SummaryPaintPolicy.needsPaint(null, "Phone is answering", 1, 2, 17));
        check(!SummaryPaintPolicy.needsPaint(shown, "Phone is answering", 1, 2, 17));
        check(SummaryPaintPolicy.needsPaint(shown, "Phone is done", 1, 2, 17));
        check(SummaryPaintPolicy.needsPaint(shown, "Phone is answering", 3, 2, 17));
        check(SummaryPaintPolicy.needsPaint(shown, "Phone is answering", 1, 4, 17));
        check(SummaryPaintPolicy.needsPaint(shown, "Phone is answering", 1, 2, 14));
        System.out.println("SummaryPaintPolicyTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
}

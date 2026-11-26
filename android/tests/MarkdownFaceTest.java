package os.opos.launcher;

public final class MarkdownFaceTest {
    public static void main(String[] args) {
        // Code is monospaced again (finding 6); bold and italic keep their faces.
        equal(MarkdownFace.MONOSPACE, MarkdownFace.forMark(AnswerMarkdownParser.CODE));
        equal(MarkdownFace.BOLD, MarkdownFace.forMark(AnswerMarkdownParser.BOLD));
        equal(MarkdownFace.ITALIC, MarkdownFace.forMark(AnswerMarkdownParser.ITALIC));
        equal(MarkdownFace.NONE, MarkdownFace.forMark(0));
        equal(MarkdownFace.NONE, MarkdownFace.forMark(99));
        // Every code range the parser emits maps to monospace.
        AnswerMarkdownParser.Result parsed = AnswerMarkdownParser.parse("Run `adb devices` now\n```\nline\n```\n");
        int code = 0;
        for (AnswerMarkdownParser.Mark mark : parsed.marks) {
            if (mark.kind == AnswerMarkdownParser.CODE) {
                code++;
                equal(MarkdownFace.MONOSPACE, MarkdownFace.forMark(mark.kind));
            }
        }
        if (code < 1) throw new AssertionError("parser produced no code mark");
        System.out.println("MarkdownFaceTest: OK");
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

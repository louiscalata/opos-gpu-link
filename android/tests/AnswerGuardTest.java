package os.opos.launcher;

public final class AnswerGuardTest {
    private static int checks;

    public static void main(String[] args) {
        StringBuilder prose = new StringBuilder();
        for (int i = 0; i < 540; i++) prose.append("word").append(i).append(' ');
        bad("repeat_char", prose + "-@" + "@".repeat(3551));
        bad("repeat_char", "@".repeat(64));
        bad("repeat_char", "8".repeat(200));
        bad("ngram_loop", "asks8alion".repeat(120));
        bad("ngram_loop", "A computer processes instructions. " + "asks8alion".repeat(8));
        bad("ngram_loop", "the same phrase again ".repeat(20));
        bad("encoding_junk", "A valid start. " + "\ufffd".repeat(6));
        bad("encoding_junk", "caf\u00c3\u00a9 and Fran\u00c3\u00a7ais");
        bad("encoding_junk", "it\u00e2\u20ac\u2122s broken");
        bad("encoding_junk", "<|im_end|><|im_end|>");
        bad("encoding_junk", "<unused12><unused12>");
        bad("encoding_junk", "good\0bad");
        bad("non_text", "\u0001\u0002\u0003\u0004".repeat(30));
        bad("non_text", "@$%!?^&<>/\\{}[]".repeat(12));
        bad("runaway_length", "x".repeat(AnswerGuard.MAX_CHARS + 1));

        good(null);
        good("");
        good("Yes.");
        good("The CPU follows instructions while memory holds the working data.\nA GPU handles many tasks in parallel.");
        good(prose.toString());
        good("ha ha ha ha");
        good("ha ha ha");
        good("-".repeat(80));
        good("|---".repeat(9));
        good("Heading\n" + "-".repeat(80) + "\n\n| Name | Value |\n|---|---|\n| CPU | 8 |\n");
        good("1. Connect the cable.\n2. Choose a model.\n3. Ask a question.\n- Wait for the answer.\n");
        good("```java\nfor (int i = 0; i < 10; i++) {\n    System.out.println(i);\n}\n```\n");
        good("```\n" + "-".repeat(80) + "\n```\n");
        good("def fib(n):\n    return n if n < 2 else fib(n - 1) + fib(n - 2)\n");
        good("La computadora ejecuta instrucciones y la memoria guarda los datos. El caf\u00e9 est\u00e1 listo. \u00a1S\u00ed!");
        good("\u4e2d\u592e\u5904\u7406\u5668\u6267\u884c\u6307\u4ee4\uff0c\u5185\u5b58\u4fdd\u5b58\u6570\u636e\u3002\u56fe\u5f62\u5904\u7406\u5668\u53ef\u4ee5\u5e76\u884c\u8ba1\u7b97\u3002");
        good("\u30b3\u30f3\u30d4\u30e5\u30fc\u30bf\u306f\u547d\u4ee4\u3092\u5b9f\u884c\u3057\u307e\u3059\u3002\u30e1\u30e2\u30ea\u306f\u30c7\u30fc\u30bf\u3092\u4fdd\u5b58\u3057\u307e\u3059\u3002");
        good("E = mc^2; x = (-b \u00b1 \u221a(b^2 - 4ac)) / (2a).\n\u2211_{i=1}^{n} i = n(n+1)/2.");
        good("A single replacement character can be quoted: \ufffd.");
        good("The token `<|im_end|>` marks the end of a message.");
        good("\u00c3gua is a word; \u00c2ngela is a name.");
        good("\ud83d\ude00 A clear answer can contain an emoji. \ud83d\ude80");
        // Only the bounded tail is inspected for shape; an old anomaly is not reclassified.
        good("@".repeat(64) + prose + prose);
        System.out.println("AnswerGuardTest: OK (" + checks + " fixtures)");
    }

    private static void bad(String expected, String text) {
        String actual = AnswerGuard.reason(text);
        checks++;
        if (!expected.equals(actual)) throw new AssertionError("Expected " + expected + ", got " + actual);
    }

    private static void good(String text) {
        String actual = AnswerGuard.reason(text);
        checks++;
        if (actual != null) throw new AssertionError("Unexpected " + actual + " for fixture " + checks);
    }
}

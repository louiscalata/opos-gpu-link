package os.opos.launcher;

public final class FollowUpPolicyTest {
    public static void main(String[] args) {
        String original = "How does a GPU speed up AI?";
        for (String bare : new String[]{"again", "Again", "again!", " retry ", "Try again", "try again.",
                "do it again", "Do that again?", "one more time", "redo", "repeat", "Please try again",
                "re-run", "same question", "don\u2019t"}) {
            boolean expected = !bare.equals("don\u2019t");
            if (FollowUpPolicy.bareFollowUp(bare) != expected) {
                throw new AssertionError("bareFollowUp(" + bare + ") should be " + expected);
            }
        }
        // A bare follow-up resends the original question, not "again".
        equal(original, FollowUpPolicy.resolve("again", original));
        equal(original, FollowUpPolicy.resolve("  Try again. ", original));
        equal(original, FollowUpPolicy.resolve("retry", original));
        // With nothing earlier to resend, the text is left alone (the app then asks for a question).
        equal("again", FollowUpPolicy.resolve("again", ""));
        equal("again", FollowUpPolicy.resolve("again", null));
        equal("again", FollowUpPolicy.resolve("again", "retry"));
        // A real question, even one that contains the word, is sent as typed.
        equal("Why do models fail again and again?", FollowUpPolicy.resolve(
                "Why do models fail again and again?", original));
        equal("Explain retry logic", FollowUpPolicy.resolve("Explain retry logic", original));
        equal("", FollowUpPolicy.resolve("", original));
        equal("", FollowUpPolicy.resolve(null, original));
        // The Retry / Try again button resends the original question.
        equal(original, FollowUpPolicy.originalQuestion(original, "something else"));
        equal(original, FollowUpPolicy.originalQuestion("", original));
        equal(original, FollowUpPolicy.originalQuestion("again", original));
        equal(original, FollowUpPolicy.originalQuestion(null, original));
        equal("", FollowUpPolicy.originalQuestion("", ""));
        System.out.println("FollowUpPolicyTest: OK");
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

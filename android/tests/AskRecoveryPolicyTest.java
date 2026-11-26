package os.opos.launcher;

import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

public final class AskRecoveryPolicyTest {
    public static void main(String[] args) {
        idlessStartupAndExpiry();
        acceptedAfterTimeout();
        oldIdSameQuestionIsNotAnAcknowledgement();
        partialAcceptanceAndReset();
        offlineAndLockedSnapshots();
        retryAndOrdinarySendShareTheGate();
        System.out.println("AskRecoveryPolicyTest: OK");
    }

    private static void idlessStartupAndExpiry() {
        AskRecoveryPolicy policy = new AskRecoveryPolicy();
        check(policy.blocksOpen("g1", true, "", "first", 1, 1_000));
        check(policy.blocksOpen("g1", true, "", "first", 1, 20_999));
        check(!policy.blocksOpen("g1", true, "", "first", 1, 21_000));
        policy.resetLocal();
        check(!policy.blocksOpen("g1", true, "", "first", 1, 21_001));
        check(policy.blocksOpen("g1", true, "", "second", 2, 21_002));
        check(policy.blocksOpen("g1", false, "", "second", 2, 21_003) == false);
        check(policy.blocksOpen("g1", true, "", "second", 2, 21_004));
        check(policy.blocksOpen("gpu", true, "id-1", "x", 1, 21_004));
        check(!policy.blocksOpen("gpu", false, "id-1", "x", 1, 21_005));
    }

    private static void acceptedAfterTimeout() {
        AskRecoveryPolicy policy = pending("old", "same", 10, "done");
        Map<String, AskRecoveryPolicy.Answer> fresh = answers(
                "new", "same", 11, "answering");
        AskRecoveryPolicy.Decision decision = policy.beforeAsk(
                AskRecoveryPolicy.AskKind.SEND, fresh, true);
        equal(AskRecoveryPolicy.Next.BIND, decision.next);
        equal(Arrays.asList("phone"), decision.advancedPanes);
        check(decision.complete);
        policy.resolve();
        equal(AskRecoveryPolicy.Next.POST, policy.beforeAsk(
                AskRecoveryPolicy.AskKind.SEND, fresh, true).next);
    }

    private static void oldIdSameQuestionIsNotAnAcknowledgement() {
        AskRecoveryPolicy policy = pending("old", "same", 10, "done");
        equal(AskRecoveryPolicy.Next.HOLD, policy.beforeAsk(
                AskRecoveryPolicy.AskKind.SEND,
                answers("old", "same", 10, "done"), true).next);
        equal(AskRecoveryPolicy.Next.HOLD, policy.beforeAsk(
                AskRecoveryPolicy.AskKind.RETRY,
                answers("old", "same", 12, "answering"), true).next);
        equal(AskRecoveryPolicy.Next.HOLD, policy.beforeAsk(
                AskRecoveryPolicy.AskKind.SEND,
                answers("new", "different", 12, "answering"), true).next);
    }

    private static void partialAcceptanceAndReset() {
        AskRecoveryPolicy policy = new AskRecoveryPolicy();
        Map<String, AskRecoveryPolicy.Answer> before = new HashMap<>();
        before.put("phone", answer("old-p", "same", 10, "done"));
        before.put("gpu", answer("old-g", "same", 10, "done"));
        policy.markUncertain(new AskRecoveryPolicy.Attempt(
                "same", Arrays.asList("phone", "gpu"), before));
        Map<String, AskRecoveryPolicy.Answer> fresh = new HashMap<>();
        fresh.put("phone", answer("new-p", "same", 11, "done"));
        fresh.put("gpu", answer("old-g", "same", 10, "done"));
        AskRecoveryPolicy.Decision partial = policy.beforeAsk(
                AskRecoveryPolicy.AskKind.RETRY, fresh, true);
        equal(AskRecoveryPolicy.Next.BIND, partial.next);
        equal(Arrays.asList("phone"), partial.advancedPanes);
        check(!partial.complete);
        check(policy.unresolved());
        fresh.put("gpu", answer("stale-g", "same", 9, "answering"));
        AskRecoveryPolicy.Decision stale = policy.beforeAsk(
                AskRecoveryPolicy.AskKind.SEND, fresh, true);
        equal(Arrays.asList("phone"), stale.advancedPanes);
        check(!stale.complete);
        fresh.put("gpu", answer("new-g", "same", 12, "answering"));
        AskRecoveryPolicy.Decision complete = policy.beforeAsk(
                AskRecoveryPolicy.AskKind.SEND, fresh, true);
        equal(Arrays.asList("phone", "gpu"), complete.advancedPanes);
        check(complete.complete);
        policy.resetLocal();
        check(!policy.unresolved());
        equal(AskRecoveryPolicy.Next.POST, policy.beforeAsk(
                AskRecoveryPolicy.AskKind.RETRY, fresh, true).next);
    }

    private static void offlineAndLockedSnapshots() {
        AskRecoveryPolicy policy = pending("old", "same", 10, "done");
        equal(AskRecoveryPolicy.Next.HOLD, policy.beforeAsk(
                AskRecoveryPolicy.AskKind.SEND, null, false).next);
        equal(AskRecoveryPolicy.Next.HOLD, policy.beforeAsk(
                AskRecoveryPolicy.AskKind.SEND,
                answers("new", "same", 11, "done"), false).next);
        policy.restoreUnknownUncertain();
        equal(AskRecoveryPolicy.Next.HOLD, policy.beforeAsk(
                AskRecoveryPolicy.AskKind.RETRY,
                answers("new", "same", 11, "done"), true).next);
    }

    private static void retryAndOrdinarySendShareTheGate() {
        AskRecoveryPolicy policy = pending("old", "same", 10, "failed");
        Map<String, AskRecoveryPolicy.Answer> unchanged =
                answers("old", "same", 10, "failed");
        for (AskRecoveryPolicy.AskKind kind : AskRecoveryPolicy.AskKind.values()) {
            equal(AskRecoveryPolicy.Next.HOLD,
                    policy.beforeAsk(kind, unchanged, true).next);
        }
        policy.resetLocal();
        for (AskRecoveryPolicy.AskKind kind : AskRecoveryPolicy.AskKind.values()) {
            equal(AskRecoveryPolicy.Next.POST,
                    policy.beforeAsk(kind, unchanged, true).next);
        }
    }

    private static AskRecoveryPolicy pending(String id, String question,
                                             double asked, String state) {
        AskRecoveryPolicy policy = new AskRecoveryPolicy();
        policy.markUncertain(new AskRecoveryPolicy.Attempt(question,
                Arrays.asList("phone"), answers(id, question, asked, state)));
        return policy;
    }

    private static Map<String, AskRecoveryPolicy.Answer> answers(
            String id, String question, double asked, String state) {
        Map<String, AskRecoveryPolicy.Answer> answers = new HashMap<>();
        answers.put("phone", answer(id, question, asked, state));
        return answers;
    }

    private static AskRecoveryPolicy.Answer answer(
            String id, String question, double asked, String state) {
        return new AskRecoveryPolicy.Answer(id, question, asked, state);
    }

    private static void check(boolean value) { if (!value) throw new AssertionError(); }
    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

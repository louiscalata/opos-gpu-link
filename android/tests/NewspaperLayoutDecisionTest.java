package os.opos.launcher;

public final class NewspaperLayoutDecisionTest {
    public static void main(String[] args) {
        check(!NewspaperLayoutDecision.compact(360, 880));
        check(NewspaperLayoutDecision.compact(360, 374));
        check(NewspaperLayoutDecision.compact(300, 1000));
        for (int count = 1; count <= 6; count++) {
            NewspaperLayoutDecision.ArticleSlot[] mosaic =
                    NewspaperLayoutDecision.articleSlots(count, false);
            NewspaperLayoutDecision.ArticleSlot[] cover =
                    NewspaperLayoutDecision.articleSlots(count, true);
            equal(count, mosaic.length);
            equal(count, cover.length);
            equal(1, mosaic[0].column);
            equal(420, mosaic[0].heightDp);
            for (int i = 0; i < count; i++) {
                equal(0, cover[i].column);
                check(mosaic[i].heightDp <= mosaic[0].heightDp);
            }
            if (count >= 3) equal(0, mosaic[2].column);
            if (count >= 4) equal(1, mosaic[3].column);
        }
        try {
            NewspaperLayoutDecision.articleSlots(7, false);
            throw new AssertionError("Seven lanes accepted");
        } catch (IllegalArgumentException expected) {}
        NewspaperLayoutDecision.ArticleSlot[] nineCover =
                NewspaperLayoutDecision.articleSlotsExtended(9, true);
        equal(9, nineCover.length);
        for (int i = 0; i < nineCover.length; i++) {
            equal(0, nineCover[i].column);
            equal(i == 0 ? 300 : 260, nineCover[i].heightDp);
        }
        equal(0f, NewspaperLayoutDecision.collapseFraction(-12, 96));
        equal(0.5f, NewspaperLayoutDecision.collapseFraction(48, 96));
        equal(1f, NewspaperLayoutDecision.collapseFraction(200, 96));
        check(NewspaperLayoutDecision.reducedMotion(0f, false));
        check(NewspaperLayoutDecision.reducedMotion(0f, true));
        check(NewspaperLayoutDecision.reducedMotion(1f, true));
        check(!NewspaperLayoutDecision.reducedMotion(1f, false));
        NewspaperLayoutDecision.RevealOnce reveal = new NewspaperLayoutDecision.RevealOnce();
        check(!reveal.enter(false));
        check(reveal.enter(true));
        check(reveal.revealed());
        check(!reveal.enter(true));
        check(!reveal.enter(false));
        check(!NewspaperLayoutDecision.animateReveal(true, false));
        check(!NewspaperLayoutDecision.animateReveal(false, true));
        check(!NewspaperLayoutDecision.animateReveal(false,
                NewspaperLayoutDecision.reducedMotion(0f, false)));
        check(!NewspaperLayoutDecision.animateReveal(false,
                NewspaperLayoutDecision.reducedMotion(1f, true)));
        check(NewspaperLayoutDecision.animateReveal(false, false));
        check(CoverLayoutPolicy.resultsSpaceDp(210, 98, true, true)
                >= CoverLayoutPolicy.MIN_RESULTS_DP);
        NewspaperLayoutDecision.FollowTail follow =
                new NewspaperLayoutDecision.FollowTail();
        check(follow.following());
        follow.userMoved(100, 99, 100);
        check(!follow.following());
        follow.userMoved(99, 100, 100);
        check(follow.following());
        follow.userMoved(100, 40, 100);
        check(!follow.following());
        follow.reset();
        check(follow.following());
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }

    private static void equal(float expected, float actual) {
        if (Math.abs(expected - actual) > 0.0001f) throw new AssertionError(actual);
    }

    private static void equal(int expected, int actual) {
        if (expected != actual) throw new AssertionError(expected + " != " + actual);
    }
}

package os.opos.launcher;

/** Small, host-testable decisions for the inner page and Flip cover. */
final class NewspaperLayoutDecision {
    private NewspaperLayoutDecision() {}

    static boolean compact(int widthDp, int heightDp) {
        // The two Flip displays have similar dp widths; height separates them.
        return widthDp < 320 || heightDp < 700;
    }

    /** Keep the normal header until larger system text can crowd its four items. */
    static boolean stackedHeader(float fontScale, boolean compactLayout,
                                 boolean landscapeLayout) {
        return fontScale >= 1.5f && !compactLayout && !landscapeLayout;
    }

    /** One complete prompt line plus its padding, with the normal row as a floor. */
    static int composerMinHeightPx(int rowPx, int fontTopPx, int fontBottomPx,
                                   int paddingTopPx, int paddingBottomPx) {
        int linePx = Math.max(0, fontBottomPx - fontTopPx);
        return Math.max(rowPx, linePx + Math.max(0, paddingTopPx)
                + Math.max(0, paddingBottomPx));
    }

    static final class ArticleSlot {
        final int column;
        final int heightDp;

        ArticleSlot(int column, int heightDp) {
            this.column = column;
            this.heightDp = heightDp;
        }
    }

    /** Index 0 is always GPU, 1 is the original phone lane, then m1..m4. */
    static ArticleSlot[] articleSlots(int answerCount, boolean compact) {
        if (answerCount < 1 || answerCount > 6) {
            throw new IllegalArgumentException("Expected 1 to 6 answer lanes");
        }
        return articleSlotsExtended(answerCount, compact);
    }

    /** Round 15 also accepts the three optional PC article lanes. */
    static ArticleSlot[] articleSlotsExtended(int answerCount, boolean compact) {
        if (answerCount < 1 || answerCount > 9) {
            throw new IllegalArgumentException("Expected 1 to 9 answer lanes");
        }
        ArticleSlot[] slots = new ArticleSlot[answerCount];
        for (int i = 0; i < answerCount; i++) {
            if (compact) slots[i] = new ArticleSlot(0, i == 0 ? 300 : 260);
            else if (i == 0) slots[i] = new ArticleSlot(1, 420);
            else if (i == 1) slots[i] = new ArticleSlot(1, 240);
            else slots[i] = new ArticleSlot((i - 2) % 2, i % 2 == 0 ? 220 : 280);
        }
        return slots;
    }

    static float collapseFraction(int scrollPx, int distancePx) {
        if (distancePx <= 0) return scrollPx > 0 ? 1f : 0f;
        return Math.max(0f, Math.min(1f, (float) scrollPx / distancePx));
    }

    static boolean reducedMotion(float animatorScale, boolean removeAnimations) {
        return animatorScale <= 0f || removeAnimations;
    }

    static final class RevealOnce {
        private boolean revealed;

        boolean enter(boolean inView) {
            if (!inView || revealed) return false;
            revealed = true;
            return true;
        }

        boolean revealed() {
            return revealed;
        }
    }

    static boolean animateReveal(boolean firstLayout, boolean reducedMotion) {
        return !firstLayout && !reducedMotion;
    }

    static final class FollowTail {
        private boolean following = true;

        void userMoved(int oldScrollY, int scrollY, int maxScrollY) {
            if (scrollY < oldScrollY) following = false;
            else if (scrollY >= maxScrollY) following = true;
        }

        void reset() {
            following = true;
        }

        boolean following() {
            return following;
        }
    }
}

package os.opos.launcher;

/**
 * Hand-off between the large masthead and the small sticky title while the page scrolls.
 * A fade before the halfway point left the app name half-hidden (or gone) with no
 * small title yet. The two never overlap, and one of them is always fully opaque.
 */
final class MastheadPolicy {
    static final float HANDOFF = 0.5f;

    private MastheadPolicy() {}

    static float bigAlpha(float collapse) {
        return clamp(collapse) < HANDOFF ? 1f : 0f;
    }

    static float smallAlpha(float collapse) {
        return clamp(collapse) >= HANDOFF ? 1f : 0f;
    }

    /** True if both titles would be drawn at the same time at this collapse fraction. */
    static boolean overlaps(float collapse) {
        return bigAlpha(collapse) > 0f && smallAlpha(collapse) > 0f;
    }

    private static float clamp(float value) {
        return Math.max(0f, Math.min(1f, value));
    }
}

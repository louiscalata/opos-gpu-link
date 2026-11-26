package os.opos.launcher;

/**
 * Modest under-damped spring for the Notes sheet. AndroidX DynamicAnimation is not
 * on the SDK-tool classpath, so this is a host-testable mass-spring step used with
 * Choreographer. Fling velocity is the initial velocity of the settle.
 */
final class NotesSpring {
    static final float STIFFNESS = 600f;
    static final float DAMPING_RATIO = 0.60f;
    static final float REST_DISPLACEMENT_PX = 0.5f;
    static final float REST_VELOCITY_PX_S = 8f;
    /** Visual overshoot allowed past the snapped height, in dp. */
    static final int OVERSHOOT_DP = 16;

    static final class Step {
        final float position;
        final float velocity;
        final boolean settled;

        Step(float position, float velocity, boolean settled) {
            this.position = position;
            this.velocity = velocity;
            this.settled = settled;
        }
    }

    private NotesSpring() {}

    static float damping(float stiffness, float dampingRatio) {
        return (float) (2f * dampingRatio * Math.sqrt(Math.max(0f, stiffness)));
    }

    /**
     * Advance one frame. {@code velocityPxPerSec} is in the same axis as {@code position}
     * (positive grows the sheet). {@code dtSeconds} is clamped by the caller.
     */
    static Step step(float position, float velocityPxPerSec, float target, float dtSeconds) {
        return step(position, velocityPxPerSec, target, dtSeconds, STIFFNESS, DAMPING_RATIO);
    }

    static Step step(float position, float velocityPxPerSec, float target, float dtSeconds,
                     float stiffness, float dampingRatio) {
        float dt = dtSeconds;
        if (!(dt > 0f)) dt = 1f / 60f;
        float x = position - target;
        float damping = damping(stiffness, dampingRatio);
        float acceleration = -stiffness * x - damping * velocityPxPerSec;
        float velocity = velocityPxPerSec + acceleration * dt;
        float next = position + velocity * dt;
        boolean settled = Math.abs(next - target) < REST_DISPLACEMENT_PX
                && Math.abs(velocity) < REST_VELOCITY_PX_S;
        if (settled) return new Step(target, 0f, true);
        return new Step(next, velocity, false);
    }
}

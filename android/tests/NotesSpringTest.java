package os.opos.launcher;

public final class NotesSpringTest {
    public static void main(String[] args) {
        if (NotesSpring.DAMPING_RATIO >= 1f) {
            throw new AssertionError("damping ratio must be under-damped for a modest bounce");
        }
        if (NotesSpring.DAMPING_RATIO < 0.5f) {
            throw new AssertionError("damping ratio too bouncy: " + NotesSpring.DAMPING_RATIO);
        }
        // From below the target with no velocity, the sheet must reach and settle.
        settle(36, 0, 200);
        settle(400, 0, 200);
        // A fling toward the target still settles there.
        settle(36, 1200, 200);
        settle(400, -1800, 36);
        // An under-damped approach overshoots at least once before rest.
        boolean overshot = false;
        float pos = 36f;
        float vel = 0f;
        float target = 200f;
        float prev = pos;
        for (int i = 0; i < 600; i++) {
            NotesSpring.Step step = NotesSpring.step(pos, vel, target, 1f / 60f);
            pos = step.position;
            vel = step.velocity;
            if (prev < target && pos > target) overshot = true;
            if (step.settled) break;
            prev = pos;
        }
        if (!overshot) throw new AssertionError("expected a modest overshoot on settle");
        equal(target, pos);
        // Already at rest stays put.
        NotesSpring.Step rest = NotesSpring.step(200f, 0f, 200f, 1f / 60f);
        if (!rest.settled || rest.position != 200f) {
            throw new AssertionError("resting spring moved");
        }
        System.out.println("NotesSpringTest: OK");
    }

    private static void settle(float from, float velocity, float target) {
        float pos = from;
        float vel = velocity;
        boolean settled = false;
        for (int i = 0; i < 600; i++) {
            NotesSpring.Step step = NotesSpring.step(pos, vel, target, 1f / 60f);
            pos = step.position;
            vel = step.velocity;
            if (step.settled) {
                settled = true;
                break;
            }
        }
        if (!settled) throw new AssertionError("did not settle from " + from + " to " + target);
        equal(target, pos);
    }

    private static void equal(float expected, float actual) {
        if (Math.abs(expected - actual) > 0.51f) {
            throw new AssertionError(expected + " != " + actual);
        }
    }
}

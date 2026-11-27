package os.opos.launcher;

public final class GpuLaneReadinessTest {
    public static void main(String[] args) {
        check(GpuLaneReadiness.ready(true, "ready"));
        check(GpuLaneReadiness.ready(true, "busy"));      // answering is not warmup
        check(GpuLaneReadiness.ready(true, null));        // older companion without a state
        check(!GpuLaneReadiness.ready(true, "loading"));  // warmup is never a stall
        check(!GpuLaneReadiness.ready(true, "copying"));
        check(!GpuLaneReadiness.ready(true, "error"));
        check(!GpuLaneReadiness.ready(false, "ready"));   // only an extra lane is live
        System.out.println("GpuLaneReadinessTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
}

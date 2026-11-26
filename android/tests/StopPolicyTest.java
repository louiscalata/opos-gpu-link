package os.opos.launcher;

import java.util.Arrays;
import java.util.Collections;

public final class StopPolicyTest {
    public static void main(String[] args) {
        // Stop pressed as the PC answer reached Done: the refused cancel is not a failure.
        check(!StopPolicy.stillRunning(Arrays.asList("pc1"), Collections.emptyList()));
        // Another lane's answer is still open but it was not one of the targets.
        check(!StopPolicy.stillRunning(Arrays.asList("pc1"), Arrays.asList("phone2")));
        // A targeted answer is still open: keep the "Try Stop again" line.
        check(StopPolicy.stillRunning(Arrays.asList("pc1", "phone1"), Arrays.asList("phone1")));
        // No fresh snapshot: we cannot tell, so keep the line.
        check(StopPolicy.stillRunning(Arrays.asList("pc1"), null));
        System.out.println("StopPolicyTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError("check failed");
    }
}

package os.opos.launcher;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

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
        // Nothing targeted is never proof that a Stop worked.
        check(StopPolicy.stillRunning(Collections.emptyList(), Collections.emptyList()));
        // Only the known old-host refusal permits individual cancellation.
        check(StopPolicy.legacyBulkUnsupported(400, "That answer was not found."));
        check(!StopPolicy.legacyBulkUnsupported(403, "That answer was not found."));
        check(!StopPolicy.legacyBulkUnsupported(400, "That answer has already ended."));
        // Keep pool lanes from starting when ending the lead answer releases the decoder.
        List<String> ids = Arrays.asList("phone", "gpu", "m1", "m2", "m3", "m4");
        Map<String, String> states = new HashMap<>();
        states.put("phone", "answering");
        states.put("gpu", "paused");
        states.put("m1", "waiting");
        states.put("m2", "queued");
        states.put("m3", "loading");
        states.put("m4", "answering");
        check(StopPolicy.waitingFirst(ids, states).equals(
                Arrays.asList("m1", "m2", "phone", "gpu", "m3", "m4")));
        System.out.println("StopPolicyTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError("check failed");
    }
}

package os.opos.launcher;

import java.util.LinkedHashMap;
import java.util.Map;

/** The Settings request is bound to the fingerprint displayed at confirmation time. */
final class ForgetAction {
    private ForgetAction() {}

    static boolean canConfirm(String shownLabel, String shownPcId,
                              String currentLabel, String currentPcId) {
        return PcFingerprint.same(shownLabel, shownPcId, currentLabel, currentPcId);
    }

    static Map<String, String> body(String shownPcId) {
        Map<String, String> fields = new LinkedHashMap<>();
        fields.put("action", "forget");
        String id = PcFingerprint.normalized(shownPcId);
        if (!id.isEmpty()) fields.put("expect", id);
        return fields;
    }
}

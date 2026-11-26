package os.opos.launcher;

/** A display-safe PC identifier when the phone snapshot exposes one. */
final class PcFingerprint {
    private PcFingerprint() {}

    static String normalized(String value) {
        return value != null && value.matches("[0-9a-f]{16}") ? value : "";
    }

    static boolean same(String label, String fingerprint,
                        String currentLabel, String currentFingerprint) {
        return label != null && label.equals(currentLabel)
                && fingerprint.equals(currentFingerprint);
    }
}

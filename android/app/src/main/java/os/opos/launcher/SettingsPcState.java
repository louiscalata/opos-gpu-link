package os.opos.launcher;

/** The PC rows in Settings are derived from one snapshot. */
final class SettingsPcState {
    enum Connection { UNKNOWN, USB_DISCONNECTED, PAIRING, CONNECTED,
        PREPARING, DISCONNECTED }
    enum Pairing { UNKNOWN, REQUESTED, CLOSED, SAVED, NONE }

    /** Only CONNECTED earns green; all other connection states use ink. */
    static UiPalette.Tone tone(Connection connection) {
        return connection == Connection.CONNECTED ? UiPalette.Tone.OK : UiPalette.Tone.NEUTRAL;
    }

    final String label;
    final String fingerprint;
    final Connection connection;
    final Pairing pairing;
    final boolean canForget;

    private SettingsPcState(String label, String fingerprint, Connection connection,
                            Pairing pairing, boolean canForget) {
        this.label = label;
        this.fingerprint = fingerprint;
        this.connection = connection;
        this.pairing = pairing;
        this.canForget = canForget;
    }

    static SettingsPcState from(boolean hasLink, boolean hasPc, boolean hasPending,
                                boolean requestsClosed, String label, String fingerprint,
                                Connection connection, boolean reachable) {
        Pairing pairing = hasPending ? Pairing.REQUESTED
                : !hasLink ? Pairing.UNKNOWN
                : requestsClosed ? Pairing.CLOSED
                : hasPc ? Pairing.SAVED : Pairing.NONE;
        Connection status = connection;
        if (!hasPc && (status == Connection.CONNECTED || status == Connection.PREPARING)) {
            status = hasLink ? Connection.DISCONNECTED : Connection.UNKNOWN;
        }
        return new SettingsPcState(hasPc && label != null ? label.trim() : "",
                hasPc ? PcFingerprint.normalized(fingerprint) : "",
                status, pairing, hasPc && reachable);
    }
}

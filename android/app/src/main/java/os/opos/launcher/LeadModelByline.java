package os.opos.launcher;

/** Adds the authenticated lead model label to the existing PC connection text. */
final class LeadModelByline {
    private LeadModelByline() {}

    static String text(String pc, String leadLabel, String defaultPc) {
        String connection = (pc == null || pc.isEmpty() ? defaultPc : pc) + " · over USB";
        return leadLabel == null || leadLabel.isEmpty()
                ? connection : leadLabel + " · " + connection;
    }
}

package os.opos.launcher;

/** Adds the authenticated lead model label to the existing PC connection text. */
final class LeadModelByline {
    private LeadModelByline() {}

    static String text(String pc, String leadLabel, String defaultPc) {
        String connection = (pc == null || pc.isEmpty() ? defaultPc : pc) + " · over USB";
        String model = PhoneByline.modelAndMaker(leadLabel);
        return model.isEmpty() ? connection : model + " · " + connection;
    }
}

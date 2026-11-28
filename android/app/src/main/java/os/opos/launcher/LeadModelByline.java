package os.opos.launcher;

/** Names the computer's lead card from its reported model label. */
final class LeadModelByline {
    private LeadModelByline() {}

    static String reportedModel(String leadLabel, String answerModel, boolean answerShown) {
        String answered = answerModel == null ? "" : answerModel.trim();
        return answerShown && !answered.isEmpty() ? answered
                : leadLabel == null ? "" : leadLabel.trim();
    }

    static boolean namedComputer(String label) {
        return label != null && !label.trim().isEmpty()
                && !"unknown".equalsIgnoreCase(label.trim())
                && !"on the PC's GPU".equals(label.trim());
    }

    static String title(String pc, String leadLabel, String defaultComputer) {
        String model = ModelDisplay.label(leadLabel);
        if (!model.isEmpty()) return model;
        return pc == null || pc.trim().isEmpty() ? defaultComputer
                : ComputerWords.title(ComputerWords.noun(pc));
    }

    static String text(String pc, String leadLabel, String defaultPc) {
        String connection = (pc == null || pc.isEmpty() ? defaultPc : pc) + " · over USB-C";
        String maker = ModelMaker.maker("", leadLabel);
        return maker.isEmpty() ? connection : maker + " · " + connection;
    }
}

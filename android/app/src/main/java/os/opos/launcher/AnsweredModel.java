package os.opos.launcher;

/**
 * Names a lane card by the model that actually wrote its answer. A lane slot can be given a
 * different model later (the phone's pool changes), so a finished answer must keep its own
 * model name rather than take the slot's current one.
 */
final class AnsweredModel {
    private AnsweredModel() {}

    /** The answer's own model when it has one, otherwise the slot's current label. */
    static String label(String slotLabel, String answerModel) {
        String answered = answerModel == null ? "" : answerModel.trim();
        return answered.isEmpty() ? (slotLabel == null ? "" : slotLabel) : answered;
    }

    /** The slot's maker belongs to the slot's model; it is dropped for an answer from another model. */
    static String maker(String slotLabel, String slotMaker, String answerModel) {
        String maker = slotMaker == null ? "" : slotMaker;
        String answered = answerModel == null ? "" : answerModel.trim();
        if (answered.isEmpty()) return maker;
        return answered.equals(slotLabel == null ? "" : slotLabel.trim()) ? maker : "";
    }
}

package os.opos.launcher;

/**
 * Name and maker of the phone's lead lane, from the running model or the model that wrote the
 * answer on screen. The service may put the maker first, for example "NVIDIA AceInstruct 1.5B".
 */
final class PhoneByline {
    private static final String[] MAKERS = {
            "Hugging Face", "Liquid AI", "Mistral AI", "Microsoft", "Alibaba", "Google", "NVIDIA",
            "Meta", "IBM"};

    private PhoneByline() {}

    private static String leadingMaker(String name) {
        for (String maker : MAKERS) {
            if (name.length() > maker.length() + 1
                    && name.regionMatches(true, 0, maker, 0, maker.length())
                    && name.charAt(maker.length()) == ' ') return maker;
        }
        return "";
    }

    static String modelName(String model) {
        String name = model == null ? "" : model.trim();
        if (name.isEmpty()) return "";
        String maker = leadingMaker(name);
        return ModelDisplay.label(maker.isEmpty() ? name : name.substring(maker.length()).trim());
    }

    static String maker(String model) {
        String name = model == null ? "" : model.trim();
        return name.isEmpty() ? "" : ModelMaker.maker(leadingMaker(name), modelName(name));
    }

    /** "Model · Maker" for the Info page. */
    static String modelAndMaker(String model) {
        return ModelMaker.details(modelName(model), maker(model), "");
    }

    /**
     * The phone card byline. {@code reported} is the service's phone.model; while the card hides an
     * older answer, that value is the hidden answer's model, so only the place is shown.
     */
    private static String cardModel(String reported, String answered, boolean hasAnswer,
                                    boolean shown) {
        String model = reported == null ? "" : reported.trim();
        String own = answered == null ? "" : answered.trim();
        if (hasAnswer && shown && !own.isEmpty()) model = own;        // the answer's own model
        else if (hasAnswer && !shown && model.equals(own)) model = ""; // a hidden answer's model
        return model;
    }

    static String titleForCard(String reported, String answered, boolean hasAnswer,
                               boolean shown, String fallback) {
        String name = modelName(cardModel(reported, answered, hasAnswer, shown));
        return name.isEmpty() ? fallback : name;
    }

    static String forCard(String reported, String answered, boolean hasAnswer, boolean shown, String where) {
        return text(cardModel(reported, answered, hasAnswer, shown), where);
    }

    static String text(String model, String where) {
        String place = where == null || where.trim().isEmpty() ? "on this phone" : where.trim();
        String namedMaker = maker(model);
        return namedMaker.isEmpty() ? place : namedMaker + " · " + place;
    }
}

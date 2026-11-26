package os.opos.launcher;

/**
 * Byline of the phone's lead lane, from the model the phone service reports (the running model,
 * or the model that wrote the answer on screen). The service names a model with its maker first,
 * for example "NVIDIA AceInstruct 1.5B", which reads "AceInstruct 1.5B · NVIDIA · on this phone".
 */
final class PhoneByline {
    private static final String[] MAKERS = {
            "Hugging Face", "Liquid AI", "Mistral AI", "Microsoft", "Alibaba", "Google", "NVIDIA",
            "Meta", "IBM"};

    private PhoneByline() {}

    /** "Model · Maker", or just the name when no known maker leads it; "" for no model. */
    static String modelAndMaker(String model) {
        String name = model == null ? "" : model.trim();
        if (name.isEmpty()) return "";
        for (String maker : MAKERS) {
            if (name.length() > maker.length() + 1 && name.regionMatches(true, 0, maker, 0, maker.length())
                    && name.charAt(maker.length()) == ' ') {
                String rest = name.substring(maker.length() + 1).trim();
                if (!rest.isEmpty()) return rest + " · " + maker;
            }
        }
        return name;
    }

    /**
     * The phone card byline. {@code reported} is the service's phone.model; while the card hides an
     * older answer, that value is the hidden answer's model, so only the place is shown.
     */
    static String forCard(String reported, String answered, boolean hasAnswer, boolean shown, String where) {
        String model = reported == null ? "" : reported.trim();
        String own = answered == null ? "" : answered.trim();
        if (hasAnswer && shown && !own.isEmpty()) model = own;        // the answer's own model
        else if (hasAnswer && !shown && model.equals(own)) model = ""; // a hidden answer's model
        return text(model, where);
    }

    static String text(String model, String where) {
        String place = where == null || where.trim().isEmpty() ? "on this phone" : where.trim();
        String named = modelAndMaker(model);
        return named.isEmpty() ? place : named + " · " + place;
    }
}

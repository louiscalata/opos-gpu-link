package os.opos.launcher;

/**
 * Byline of the phone's lead lane, from the model the phone service reports (the running model,
 * or the model that wrote the answer on screen). The service names a model with its maker first,
 * for example "NVIDIA AceInstruct 1.5B", which reads "AceInstruct 1.5B · NVIDIA · on this phone".
 */
final class PhoneByline {
    private static final String[] MAKERS = {
            "Hugging Face", "Liquid AI", "Mistral AI", "Microsoft", "Alibaba", "Google", "NVIDIA",
            "Meta", "IBM", "Qwen"};

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

    static String text(String model, String where) {
        String place = where == null || where.trim().isEmpty() ? "on this phone" : where.trim();
        String named = modelAndMaker(model);
        return named.isEmpty() ? place : named + " · " + place;
    }
}

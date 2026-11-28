package os.opos.launcher;

/**
 * Persisted typography and theme choices. Offline only: a string store, typically
 * SharedPreferences. Type is fixed at H5+S5+B5; theme defaults to Dark.
 */
final class UiSettings {
    interface Store {
        String get(String key, String fallback);
        void put(String key, String value);
    }

    static final String KEY_TYPOGRAPHY = "ui_typography";
    static final String KEY_THEME = "ui_theme";
    /** Experimental Design lab view; anything but a known mode reads as Off. */
    static final String KEY_DESIGN_LAB = "ui_design_lab";
    static final String THEME_DARK = "dark";
    static final String THEME_LIGHT = "light";
    static final String THEME_SYSTEM = "system";

    private final Store store;

    UiSettings(Store store) {
        this.store = store;
    }

    TypeChoice typography() {
        return TypeChoice.defaults();
    }

    String themePreference() {
        String value = store.get(KEY_THEME, THEME_DARK);
        if (THEME_LIGHT.equals(value) || THEME_SYSTEM.equals(value)) return value;
        return THEME_DARK;
    }

    String designLab() {
        return DesignLab.parseMode(store.get(KEY_DESIGN_LAB, DesignLab.OFF));
    }

    boolean setDesignLab(String id) {
        if (id == null || !DesignLab.MODES.contains(id)) return false;
        store.put(KEY_DESIGN_LAB, id);
        return true;
    }

    boolean setTypography(String id) {
        return TypeChoice.DEFAULT.equals(id);
    }

    boolean setTheme(String id) {
        if (!THEME_DARK.equals(id) && !THEME_LIGHT.equals(id) && !THEME_SYSTEM.equals(id)) {
            return false;
        }
        store.put(KEY_THEME, id);
        return true;
    }

    UiPalette.Theme resolvedTheme(boolean systemDark) {
        return UiPalette.resolve(themePreference(), systemDark);
    }

    UiPalette palette(boolean systemDark) {
        return new UiPalette(resolvedTheme(systemDark));
    }

    static String themeCaption(String id) {
        if (THEME_LIGHT.equals(id)) return "Light";
        if (THEME_SYSTEM.equals(id)) return "Follow system";
        return "Dark (default)";
    }
}

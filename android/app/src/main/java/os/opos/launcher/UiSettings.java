package os.opos.launcher;

/**
 * Persisted typography and theme choices. Offline only: a string store, typically
 * SharedPreferences. Invalid values fall back to the defaults (H5+S5+B5, Dark).
 */
final class UiSettings {
    interface Store {
        String get(String key, String fallback);
        void put(String key, String value);
    }

    static final String KEY_TYPOGRAPHY = "ui_typography";
    static final String KEY_THEME = "ui_theme";
    static final String THEME_DARK = "dark";
    static final String THEME_LIGHT = "light";
    static final String THEME_SYSTEM = "system";

    private final Store store;

    UiSettings(Store store) {
        this.store = store;
    }

    TypeChoice typography() {
        return TypeChoice.parse(store.get(KEY_TYPOGRAPHY, TypeChoice.DEFAULT));
    }

    String themePreference() {
        String value = store.get(KEY_THEME, THEME_DARK);
        if (THEME_LIGHT.equals(value) || THEME_SYSTEM.equals(value)) return value;
        return THEME_DARK;
    }

    boolean setTypography(String id) {
        if (!TypeChoice.OPTIONS.contains(id)) return false;
        store.put(KEY_TYPOGRAPHY, id);
        return true;
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

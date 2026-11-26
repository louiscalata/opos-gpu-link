package os.opos.launcher;

import java.util.LinkedHashMap;
import java.util.Map;

public final class UiSettingsTest {
    public static void main(String[] args) {
        Memory store = new Memory();
        UiSettings settings = new UiSettings(store);
        equal(TypeChoice.DEFAULT, settings.typography().id);
        equal("H5", settings.typography().headerId);
        equal("S5", settings.typography().subheaderId);
        equal("B5", settings.typography().bodyId);
        equal(TypeConfig.HEADER + "+" + TypeConfig.SUBHEADER + "+" + TypeConfig.BODY,
                TypeChoice.DEFAULT);
        equal(UiSettings.THEME_DARK, settings.themePreference());
        equal(UiPalette.Theme.DARK, settings.resolvedTheme(false));

        check(settings.setTypography("H7+S7+B7"));
        equal("H7+S7+B7", settings.typography().id);
        equal("H7", settings.typography().header().id);
        check(settings.setTypography(TypeChoice.FABLE));
        equal("H5", settings.typography().headerId);
        equal("S6", settings.typography().subheaderId);
        equal("B7", settings.typography().bodyId);
        check(!settings.setTypography("H1+S1+B1"));
        equal(TypeChoice.FABLE, settings.typography().id);

        check(settings.setTheme(UiSettings.THEME_LIGHT));
        equal(UiSettings.THEME_LIGHT, settings.themePreference());
        equal(UiPalette.Theme.LIGHT, settings.resolvedTheme(true));
        check(settings.setTheme(UiSettings.THEME_SYSTEM));
        equal(UiPalette.Theme.DARK, settings.resolvedTheme(true));
        equal(UiPalette.Theme.LIGHT, settings.resolvedTheme(false));
        check(!settings.setTheme("sepia"));
        equal(UiSettings.THEME_SYSTEM, settings.themePreference());

        store.values.put(UiSettings.KEY_TYPOGRAPHY, "not-a-set");
        store.values.put(UiSettings.KEY_THEME, "rainbow");
        equal(TypeChoice.DEFAULT, settings.typography().id);
        equal(UiSettings.THEME_DARK, settings.themePreference());

        equal("Optical broadsheet (default)", TypeChoice.caption("H5+S5+B5"));
        equal("Fable", TypeChoice.caption(TypeChoice.FABLE));
        equal("Dark (default)", UiSettings.themeCaption(UiSettings.THEME_DARK));
        equal("Light", UiSettings.themeCaption(UiSettings.THEME_LIGHT));
        equal("Follow system", UiSettings.themeCaption(UiSettings.THEME_SYSTEM));
        check(TypeChoice.defaults().isDefault());
        check(TypeChoice.OPTIONS.size() == 5);
        System.out.println("UiSettingsTest: OK");
    }

    private static final class Memory implements UiSettings.Store {
        final Map<String, String> values = new LinkedHashMap<>();
        @Override public String get(String key, String fallback) {
            return values.containsKey(key) ? values.get(key) : fallback;
        }
        @Override public void put(String key, String value) { values.put(key, value); }
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected " + expected + ", got " + actual);
        }
    }
}

package os.opos.launcher;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;
import org.w3c.dom.NodeList;

/**
 * Fails if any hue other than the approved reds and greens appears in res/ or
 * in production colour literals. Grays, black and white are allowed. Covers
 * both theme variants stored in colors.xml and {@link UiPalette}.
 */
public final class PaletteHueTest {
    private static final Path ROOT = Path.of("app/src/main");
    private static final Pattern JAVA_STRING = Pattern.compile("\"(#[0-9A-Fa-f]{3,8})\"");

    public static void main(String[] args) throws Exception {
        List<String> bad = new ArrayList<>();
        Document colors = xml(ROOT.resolve("res/values/colors.xml"));
        NodeList definitions = colors.getElementsByTagName("color");
        equal(UiPalette.BLACK, named(definitions, "newspaper_paper"));
        equal(UiPalette.WHITE, named(definitions, "newspaper_ink"));
        equal(UiPalette.LABEL_DARK, named(definitions, "you_asked_label"));
        equal(UiPalette.NOTES_RULE_DARK, named(definitions, "notes_rule"));
        equal(UiPalette.STROKE, named(definitions, "newspaper_stroke"));
        equal(UiPalette.ERROR_DARK, named(definitions, "newspaper_error"));
        equal(UiPalette.OK_DARK, named(definitions, "newspaper_ok"));
        equal(UiPalette.WHITE, named(definitions, "newspaper_paper_light"));
        equal(UiPalette.BLACK, named(definitions, "newspaper_ink_light"));
        equal(UiPalette.LABEL_LIGHT, named(definitions, "you_asked_label_light"));
        equal(UiPalette.NOTES_RULE_LIGHT, named(definitions, "notes_rule_light"));
        equal(UiPalette.STROKE, named(definitions, "newspaper_stroke_light"));
        equal(UiPalette.ERROR_LIGHT, named(definitions, "newspaper_error_light"));
        equal(UiPalette.OK_LIGHT, named(definitions, "newspaper_ok_light"));
        for (int i = 0; i < definitions.getLength(); i++) {
            org.w3c.dom.Element element = (org.w3c.dom.Element) definitions.item(i);
            String value = element.getTextContent().trim();
            if (!UiPalette.allowedHex(value)) {
                bad.add("colors.xml " + element.getAttribute("name") + "=" + value);
            }
        }

        try (var paths = Files.walk(ROOT.resolve("res"))) {
            for (Path path : paths.filter(p -> p.toString().endsWith(".xml")).toList()) {
                if (path.endsWith("values/colors.xml")) continue;
                Matcher matcher = UiPalette.hexMatcher(Files.readString(path));
                while (matcher.find()) {
                    bad.add(path + " literal " + matcher.group());
                }
            }
        }

        try (var paths = Files.walk(ROOT.resolve("java"))) {
            for (Path path : paths.filter(p -> p.toString().endsWith(".java")).toList()) {
                String source = stripComments(Files.readString(path));
                Matcher strings = JAVA_STRING.matcher(source);
                while (strings.find()) {
                    String hex = strings.group(1);
                    if (!UiPalette.allowedHex(hex)) {
                        bad.add(path + " string " + hex);
                    }
                }
            }
        }

        if (!bad.isEmpty()) {
            throw new AssertionError("Disallowed hues:\n" + String.join("\n", bad));
        }
        System.out.println("PaletteHueTest: OK");
    }

    private static String stripComments(String source) {
        String noBlocks = source.replaceAll("/\\*.*?\\*/", " ");
        return noBlocks.replaceAll("//[^\\n]*", " ");
    }

    private static Document xml(Path path) throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        return factory.newDocumentBuilder().parse(path.toFile());
    }

    private static String named(NodeList list, String name) {
        for (int i = 0; i < list.getLength(); i++) {
            org.w3c.dom.Element element = (org.w3c.dom.Element) list.item(i);
            if (name.equals(element.getAttribute("name"))) return element.getTextContent().trim();
        }
        throw new AssertionError("Missing color: " + name);
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError("expected " + expected + ", got " + actual);
        }
    }
}

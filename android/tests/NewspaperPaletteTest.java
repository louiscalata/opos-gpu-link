package os.opos.launcher;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.regex.Pattern;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

public final class NewspaperPaletteTest {
    private static final Path RES = Path.of("app/src/main/res");
    private static final String PAPER = "@color/newspaper_paper";
    private static final String INK = "@color/newspaper_ink";

    public static void main(String[] args) throws Exception {
        Document colors = xml("values/colors.xml");
        NodeList definitions = colors.getElementsByTagName("color");
        equal(12, definitions.getLength(), "black, white, grays, and red/green for both themes");
        equal("#000000", named(definitions, "newspaper_paper").getTextContent().trim(),
                "black page");
        equal("#FFFFFF", named(definitions, "newspaper_ink").getTextContent().trim(),
                "white ink");
        equal("#BFBFBF", named(definitions, "you_asked_label").getTextContent().trim(),
                "asked label exception");
        equal("#5C5C5C", named(definitions, "newspaper_stroke").getTextContent().trim(),
                "recessive box stroke exception (darker than the text)");
        equal("#FF5A52", named(definitions, "newspaper_error").getTextContent().trim(),
                "error red on black");
        equal("#3DDC84", named(definitions, "newspaper_ok").getTextContent().trim(),
                "success green on black");
        equal("#FFFFFF", named(definitions, "newspaper_paper_light").getTextContent().trim(),
                "light page");
        equal("#000000", named(definitions, "newspaper_ink_light").getTextContent().trim(),
                "light ink");
        equal("#5C5C5C", named(definitions, "you_asked_label_light").getTextContent().trim(),
                "light label");
        equal("#5C5C5C", named(definitions, "newspaper_stroke_light").getTextContent().trim(),
                "light stroke");
        equal("#B3261E", named(definitions, "newspaper_error_light").getTextContent().trim(),
                "error red on white");
        equal("#0F7A45", named(definitions, "newspaper_ok_light").getTextContent().trim(),
                "success green on white");
        Document strings = xml("values/strings.xml");
        equal("Ask the models…", named(strings.getElementsByTagName("string"),
                "question_hint").getTextContent(), "question hint");
        equal("Ask the models", named(strings.getElementsByTagName("string"),
                "ask_both").getTextContent(), "ask both label");

        Document styles = xml("values/styles.xml");
        for (String theme : new String[]{"NewspaperTheme", "InfoDialogTheme"}) {
            Element style = named(styles.getElementsByTagName("style"), theme);
            equal(PAPER, item(style, "android:windowBackground"), theme + " background");
            equal(PAPER, item(style, "android:statusBarColor"), theme + " status bar");
            equal(PAPER, item(style, "android:navigationBarColor"), theme + " navigation bar");
            equal(INK, item(style, "android:textColorPrimary"), theme + " ink");
            equal("false", item(style, "android:windowLightStatusBar"), theme + " light status");
            equal("false", item(style, "android:windowLightNavigationBar"),
                    theme + " light navigation");
        }

        equal(PAPER, xml("layout/models.xml").getDocumentElement()
                .getAttribute("android:background"), "front and cover page");
        equal(PAPER, xml("layout/gpu_link_info.xml").getDocumentElement()
                .getAttribute("android:background"), "Settings page");
        equal(INK, child(xml("drawable/newspaper_primary.xml"), "solid")
                .getAttribute("android:color"), "inverted primary fill");
        equal(PAPER, child(xml("drawable/newspaper_outline.xml"), "solid")
                .getAttribute("android:color"), "outline fill");
        equal("@color/newspaper_stroke", child(xml("drawable/newspaper_outline.xml"), "stroke")
                .getAttribute("android:color"), "outline stroke");
        equal("@dimen/card_stroke", child(xml("drawable/newspaper_outline.xml"), "stroke")
                .getAttribute("android:width"), "outline hairline");
        equal(PAPER, child(xml("drawable/newspaper_panel.xml"), "solid")
                .getAttribute("android:color"), "lane panel fill");
        equal("@color/newspaper_stroke", child(xml("drawable/newspaper_panel.xml"), "stroke")
                .getAttribute("android:color"), "lane panel stroke");
        equal("@dimen/card_stroke", child(xml("drawable/newspaper_panel.xml"), "stroke")
                .getAttribute("android:width"), "lane panel hairline");

        Document front = xml("layout/models.xml");
        boolean sawSend = false;
        for (int i = 0; i < front.getElementsByTagName("Button").getLength(); i++) {
            Element button = (Element) front.getElementsByTagName("Button").item(i);
            String background = button.getAttribute("android:background");
            if ("@drawable/newspaper_primary".equals(background)) {
                equal(PAPER, button.getAttribute("android:textColor"), "primary button text");
                if ("@+id/ask".equals(button.getAttribute("android:id"))) sawSend = true;
            } else if ("@drawable/newspaper_outline".equals(background)) {
                equal(INK, button.getAttribute("android:textColor"), "outline button text");
            }
        }
        check(sawSend, "Send uses the inverted primary fill");

        Pattern literal = Pattern.compile("#[0-9A-Fa-f]{6,8}\\b");
        try (var paths = Files.walk(RES)) {
            for (Path path : paths.filter(p -> p.toString().endsWith(".xml")).toList()) {
                if (path.endsWith("values/colors.xml")) continue;
                check(!literal.matcher(Files.readString(path)).find(),
                        "color literal outside colors.xml: " + path);
            }
        }
        System.out.println("NewspaperPaletteTest: OK");
    }

    private static Document xml(String relative) throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        return factory.newDocumentBuilder().parse(RES.resolve(relative).toFile());
    }

    private static Element named(NodeList list, String name) {
        for (int i = 0; i < list.getLength(); i++) {
            Element element = (Element) list.item(i);
            if (name.equals(element.getAttribute("name"))) return element;
        }
        throw new AssertionError("Missing resource: " + name);
    }

    private static Element child(Document document, String tag) {
        return (Element) document.getElementsByTagName(tag).item(0);
    }

    private static String item(Element style, String name) {
        return named(style.getElementsByTagName("item"), name).getTextContent().trim();
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void equal(Object expected, Object actual, String message) {
        if (!expected.equals(actual)) {
            throw new AssertionError(message + ": expected " + expected + ", got " + actual);
        }
    }
}

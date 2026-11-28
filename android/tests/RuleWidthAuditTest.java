package os.opos.launcher;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

/** Keeps dividers and notepad rules at the same hairline width as card borders. */
public final class RuleWidthAuditTest {
    private static final Path MAIN = Path.of("app/src/main");
    private static final Pattern RAW_JAVA_RULE = Pattern.compile(
            "\\bMATCH_PARENT\\s*,\\s*dp\\s*\\(\\s*1\\s*\\)|\\.height\\s*=\\s*dp\\s*\\(\\s*1\\s*\\)");
    private static final Pattern RAW_XML_RULE = Pattern.compile(
            "android:layout_height\\s*=\\s*\"1dp\"");

    public static void main(String[] args) throws Exception {
        check(RAW_JAVA_RULE.matcher("MATCH_PARENT, dp(1)").find(), "Java scan works");
        check(RAW_XML_RULE.matcher("android:layout_height=\"1dp\"").find(), "XML scan works");

        List<String> hits = new ArrayList<>();
        try (var files = Files.walk(MAIN.resolve("java"))) {
            for (Path file : files.filter(p -> p.toString().endsWith(".java")).toList()) {
                scan(file, RAW_JAVA_RULE, hits);
            }
        }
        try (var files = Files.walk(MAIN.resolve("res/layout"))) {
            for (Path file : files.filter(p -> p.toString().endsWith(".xml")).toList()) {
                scan(file, RAW_XML_RULE, hits);
            }
        }
        check(hits.isEmpty(), "Raw 1dp rule heights: " + hits);

        Document spacing = xml("res/values/spacing.xml");
        equal(LaneCardLayout.STROKE_DP + "dp",
                named(spacing.getElementsByTagName("dimen"), "card_stroke").getTextContent().trim(),
                "card stroke token");
        Document info = xml("res/layout/gpu_link_info.xml");
        Element rule = withId(info.getElementsByTagName("View"), "@+id/info_rule");
        equal("@dimen/card_stroke", rule.getAttribute("android:layout_height"), "Info rule height");
        equal("@color/newspaper_stroke", rule.getAttribute("android:background"), "Info rule color");
        for (String drawable : new String[] {"newspaper_panel.xml", "newspaper_outline.xml"}) {
            Element stroke = (Element) xml("res/drawable/" + drawable)
                    .getElementsByTagName("stroke").item(0);
            equal("@dimen/card_stroke", stroke.getAttribute("android:width"), drawable + " width");
            equal("@color/newspaper_stroke", stroke.getAttribute("android:color"), drawable + " color");
        }
        String notes = Files.readString(MAIN.resolve("java/os/opos/launcher/LinedNotesEditText.java"));
        check(notes.contains("getDimensionPixelSize(R.dimen.card_stroke)"), "Notes rule width");
        check(notes.contains("R.color.newspaper_stroke"), "Notes rule color");
        String activity = Files.readString(MAIN.resolve("java/os/opos/launcher/MainActivity.java"));
        check(activity.contains("LayoutParams.MATCH_PARENT, cardStrokePx()"), "Java rule height");
        check(activity.contains("if (infoRule != null) infoRule.setBackgroundColor("
                + "themeColor(R.color.newspaper_stroke))"), "Info rule theme color");
        System.out.println("RuleWidthAuditTest: OK");
    }

    private static void scan(Path file, Pattern pattern, List<String> hits) throws Exception {
        String source = Files.readString(file);
        Matcher match = pattern.matcher(source);
        while (match.find()) {
            int line = 1;
            for (int i = 0; i < match.start(); i++) if (source.charAt(i) == '\n') line++;
            hits.add(file + ":" + line + " " + match.group());
        }
    }

    private static Document xml(String relative) throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        return factory.newDocumentBuilder().parse(MAIN.resolve(relative).toFile());
    }

    private static Element named(NodeList list, String name) {
        for (int i = 0; i < list.getLength(); i++) {
            Element element = (Element) list.item(i);
            if (name.equals(element.getAttribute("name"))) return element;
        }
        throw new AssertionError("Missing resource: " + name);
    }

    private static Element withId(NodeList list, String id) {
        for (int i = 0; i < list.getLength(); i++) {
            Element element = (Element) list.item(i);
            if (id.equals(element.getAttribute("android:id"))) return element;
        }
        throw new AssertionError("Missing view: " + id);
    }

    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static void equal(Object expected, Object actual, String message) {
        if (!expected.equals(actual)) {
            throw new AssertionError(message + ": expected " + expected + ", got " + actual);
        }
    }
}

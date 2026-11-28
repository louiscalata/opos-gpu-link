package os.opos.launcher;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/** Keep app text on named type roles, with no shadow or synthesized styles. */
public final class TypographyAuditTest {
    private static final String[] FORBIDDEN = {
            "setShadowLayer", "setFakeBoldText", "android:shadow", "android:textStyle",
            "new StyleSpan(", "Typeface.BOLD", "Typeface.ITALIC", "Typeface.BOLD_ITALIC",
            "setLayerType", "BlurMaskFilter", "RenderEffect", "setElevation(", "android:elevation",
            "android:fontFamily=\"sans-serif", "setTypeface(null"
    };
    private static final Pattern RAW_SP = Pattern.compile("\\b\\d+(?:\\.\\d+)?sp\\b");
    private static final Pattern RAW_TEXT_SIZE = Pattern.compile(
            "\\.setTextSize\\s*\\(\\s*(?:TypedValue\\.COMPLEX_UNIT_SP\\s*,\\s*)?\\d+(?:\\.\\d+)?f?\\s*\\)");
    private static final Pattern RAW_ROLE_SIZE = Pattern.compile(
            "\\btypography\\.(?:display|headline|body)\\s*\\([^;]*?,\\s*\\d+(?:\\.\\d+)?f?\\s*\\)");
    private static final String CAPS_TRACKING_LITERAL = "0.08f";

    public static void main(String[] args) throws IOException {
        // Guard both XML attributes and Java calls; display exceptions must use named constants.
        equal("18sp", first(RAW_SP, "android:textSize=\"18sp\""));
        equal(".setTextSize(17)", first(RAW_TEXT_SIZE, "view.setTextSize(17)"));
        equal("typography.body(view, 20)", first(RAW_ROLE_SIZE,
                "typography.body(view, 20)"));
        List<String> hits = new ArrayList<>();
        int capsTrackingLiterals = 0;
        try (Stream<Path> files = Files.walk(Path.of("app/src/main"))) {
            for (Path file : (Iterable<Path>) files.filter(p -> {
                String name = p.toString();
                return name.endsWith(".java") || name.endsWith(".xml");
            })::iterator) {
                String text = Files.readString(file);
                int at = -1;
                while ((at = text.indexOf(CAPS_TRACKING_LITERAL, at + 1)) >= 0) {
                    capsTrackingLiterals++;
                    if (!file.getFileName().toString().equals("TypeConfig.java")) {
                        hits.add(file + ": caps tracking literal outside TypeConfig");
                    }
                }
                for (String token : FORBIDDEN) {
                    at = text.indexOf(token);
                    // Popup elevation 0 removes the platform shadow; that one call is allowed.
                    if (at >= 0 && !(token.equals("setElevation(") && text.contains("setElevation(0)")
                            && text.indexOf(token, at + 1) < 0)) {
                        hits.add(file + ": " + token);
                    }
                }
                for (Pattern pattern : new Pattern[] {RAW_SP, RAW_TEXT_SIZE, RAW_ROLE_SIZE}) {
                    String raw = first(pattern, text);
                    if (raw != null) hits.add(file + ": raw type size " + raw);
                }
            }
        }
        if (capsTrackingLiterals != 1) {
            hits.add("expected one caps tracking literal, found " + capsTrackingLiterals);
        }
        String typeConfig = Files.readString(Path.of(
                "app/src/main/java/os/opos/launcher/TypeConfig.java"));
        if (!typeConfig.contains("static final float S5_CAPS_TRACKING = 0.08f;")) {
            hits.add("caps tracking literal must be the S5 token declaration");
        }
        if (!hits.isEmpty()) throw new AssertionError("Typography audit found: " + hits);
        // Emphasis and italics are real bundled cuts for the body face.
        equal("textSemibold", TypeConfig.emphasisFace(TypeConfig.body().face));
        equal("textItalic", TypeConfig.italicFace(TypeConfig.body().face));
        equal("smTextBold", TypeConfig.emphasisFace(TypeConfig.FACE_SM_TEXT_REGULAR));
        equal("newsreader16Italic", TypeConfig.italicFace(TypeConfig.FACE_NEWSREADER_16_REGULAR));
        System.out.println("TypographyAuditTest: OK");
    }

    private static String first(Pattern pattern, String text) {
        Matcher match = pattern.matcher(text);
        return match.find() ? match.group() : null;
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

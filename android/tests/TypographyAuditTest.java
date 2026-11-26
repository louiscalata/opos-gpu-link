package os.opos.launcher;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Stream;

/** No shadow, glow or synthesized bold/italic anywhere in the app sources. */
public final class TypographyAuditTest {
    private static final String[] FORBIDDEN = {
            "setShadowLayer", "setFakeBoldText", "android:shadow", "android:textStyle",
            "new StyleSpan(", "Typeface.BOLD", "Typeface.ITALIC", "Typeface.BOLD_ITALIC",
            "setLayerType", "BlurMaskFilter", "RenderEffect", "setElevation(", "android:elevation",
            "android:fontFamily=\"sans-serif", "setTypeface(null"
    };

    public static void main(String[] args) throws IOException {
        List<String> hits = new ArrayList<>();
        try (Stream<Path> files = Files.walk(Path.of("app/src/main"))) {
            for (Path file : (Iterable<Path>) files.filter(p -> {
                String name = p.toString();
                return name.endsWith(".java") || name.endsWith(".xml");
            })::iterator) {
                String text = Files.readString(file);
                for (String token : FORBIDDEN) {
                    int at = text.indexOf(token);
                    // Popup elevation 0 removes the platform shadow; that one call is allowed.
                    if (at >= 0 && !(token.equals("setElevation(") && text.contains("setElevation(0)")
                            && text.indexOf(token, at + 1) < 0)) {
                        hits.add(file + ": " + token);
                    }
                }
            }
        }
        if (!hits.isEmpty()) throw new AssertionError("Shadow or synthesized style found: " + hits);
        // Emphasis and italics are real bundled cuts for the body face.
        equal("textSemibold", TypeConfig.emphasisFace(TypeConfig.body().face));
        equal("textItalic", TypeConfig.italicFace(TypeConfig.body().face));
        equal("smTextBold", TypeConfig.emphasisFace(TypeConfig.FACE_SM_TEXT_REGULAR));
        equal("newsreader16Italic", TypeConfig.italicFace(TypeConfig.FACE_NEWSREADER_16_REGULAR));
        System.out.println("TypographyAuditTest: OK");
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

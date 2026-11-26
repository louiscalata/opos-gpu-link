package os.opos.launcher;

import android.content.Context;
import android.content.res.Resources;
import android.graphics.Typeface;
import android.text.Layout;
import android.util.TypedValue;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;

/** The bundled faces and the page's repeatable text roles. */
final class Typography {
    final Typeface displayBlack;
    final Typeface subheadBold;
    final Typeface subheadSemibold;
    final Typeface smTextRegular;
    final Typeface smTextBold;
    final Typeface textRegular;
    final Typeface textSemibold;
    final Typeface textItalic;
    final Typeface interRegular;
    final Typeface interMedium;
    final Typeface interSemibold;
    final Typeface jetbrainsMonoMedium;
    final Typeface newsreader72Semibold;
    final Typeface newsreader16Regular;
    final Typeface newsreader16Italic;
    private boolean cover;
    private TypeChoice choice = TypeChoice.defaults();

    Typography(Context context) {
        Resources resources = context.getResources();
        displayBlack = resources.getFont(R.font.source_serif_display_black);
        subheadBold = resources.getFont(R.font.source_serif_subhead_bold);
        subheadSemibold = resources.getFont(R.font.source_serif_subhead_semibold);
        smTextRegular = resources.getFont(R.font.source_serif_smtext_regular);
        smTextBold = resources.getFont(R.font.source_serif_smtext_bold);
        textRegular = resources.getFont(R.font.source_serif_text_regular);
        textSemibold = resources.getFont(R.font.source_serif_text_semibold);
        textItalic = resources.getFont(R.font.source_serif_text_italic);
        interRegular = resources.getFont(R.font.inter_regular);
        interMedium = resources.getFont(R.font.inter_medium);
        interSemibold = resources.getFont(R.font.inter_semibold);
        jetbrainsMonoMedium = resources.getFont(R.font.jetbrains_mono_medium);
        newsreader72Semibold = resources.getFont(R.font.newsreader_72pt_semibold);
        newsreader16Regular = resources.getFont(R.font.newsreader_16pt_regular);
        newsreader16Italic = resources.getFont(R.font.newsreader_16pt_italic);
    }

    void useCover(boolean coverMode) {
        cover = coverMode;
    }

    void useChoice(TypeChoice typeChoice) {
        choice = typeChoice == null ? TypeChoice.defaults() : typeChoice;
    }

    TypeChoice choice() {
        return choice;
    }

    int headingSp() { return choice.header().size(cover); }
    int labelSp() { return choice.subheader().size(cover); }
    int bodySp() { return choice.body().size(cover); }

    void defaults(View root) {
        if (root instanceof TextView) {
            TextView text = (TextView) root;
            Typeface current = text.getTypeface();
            text.setTypeface(current != null && current.isBold() ? interSemibold : interMedium);
        }
        if (root instanceof ViewGroup) {
            ViewGroup group = (ViewGroup) root;
            for (int i = 0; i < group.getChildCount(); i++) defaults(group.getChildAt(i));
        }
    }

    void display(TextView text, int sizeSp) {
        text.setTypeface(displayBlack);
        text.setTextSize(sizeSp);
        text.setLineSpacing(0, 1f);
        text.setLetterSpacing(-0.01f);
        text.setAllCaps(false);
    }

    void headline(TextView text, int sizeSp) {
        apply(text, choice.header(), sizeSp, choice.header().allCaps, choice.header().face);
    }

    void kicker(TextView text) {
        TypeConfig.Role role = choice.subheader();
        apply(text, role, role.size(cover), role.allCaps, role.face);
    }

    void state(TextView text) {
        TypeConfig.Role role = choice.subheader();
        // Whole-line mono is too wide for a 165 dp column. Use the subheader
        // face with tnum; S8 is already mono. numeralFace remains available
        // for a tok/s span.
        apply(text, role, role.size(cover), false, role.face);
        tabular(text);
    }

    void byline(TextView text) {
        TypeConfig.Role role = choice.subheader();
        String bylineFace = role.face;
        if ("S6".equals(role.id)) bylineFace = TypeConfig.FACE_NEWSREADER_16_ITALIC;
        else if ("S5".equals(role.id) || "S7".equals(role.id)) bylineFace = TypeConfig.FACE_TEXT_ITALIC;
        apply(text, role, role.size(cover), false, bylineFace);
    }

    /** Subheader style for GB-22's per-lane retry control; never forced to caps. */
    void retry(TextView text) {
        TypeConfig.Role role = choice.subheader();
        apply(text, role, role.size(cover), false, role.face);
    }

    void body(TextView text, int sizeSp) {
        apply(text, choice.body(), sizeSp, false, choice.body().face);
        text.setIncludeFontPadding(true);
        text.setBreakStrategy(Layout.BREAK_STRATEGY_HIGH_QUALITY);
        // Rag-right newspaper body: no hyphenation.
        text.setHyphenationFrequency(Layout.HYPHENATION_FREQUENCY_NONE);
    }

    void tabular(TextView text) {
        text.setFontFeatureSettings("tnum");
    }

    /**
     * Role lineHeight is a typographic multiple of the em size (baseline
     * distance / sizeSp). {@code setLineSpacing(0, m)} would instead multiply
     * the font's own metrics, so 1.35 can land near 1.9 em.
     */
    void applyLineHeight(TextView text, int sizeSp, float lineHeight) {
        int px = Math.round(TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_SP,
                sizeSp * lineHeight,
                text.getResources().getDisplayMetrics()));
        text.setLineHeight(Math.max(px, 1));
    }


    private void apply(TextView text, TypeConfig.Role role, int sizeSp, boolean allCaps, String faceId) {
        text.setTypeface(face(faceId));
        text.setTextSize(sizeSp);
        applyLineHeight(text, sizeSp, role.lineHeight);
        text.setLetterSpacing(role.letterSpacing);
        text.setAllCaps(allCaps);
        if (role.tabular) tabular(text);
        else text.setFontFeatureSettings(null);
    }

    Typeface face(String id) {
        if (id == null) return textRegular;
        switch (id) {
            case TypeConfig.FACE_DISPLAY_BLACK: return displayBlack;
            case TypeConfig.FACE_SUBHEAD_BOLD: return subheadBold;
            case TypeConfig.FACE_SUBHEAD_SEMIBOLD: return subheadSemibold;
            case TypeConfig.FACE_SM_TEXT_BOLD: return smTextBold;
            case TypeConfig.FACE_SM_TEXT_REGULAR: return smTextRegular;
            case TypeConfig.FACE_TEXT_SEMIBOLD: return textSemibold;
            case TypeConfig.FACE_TEXT_ITALIC: return textItalic;
            case TypeConfig.FACE_INTER_REGULAR: return interRegular;
            case TypeConfig.FACE_INTER_MEDIUM: return interMedium;
            case TypeConfig.FACE_INTER_SEMIBOLD: return interSemibold;
            case TypeConfig.FACE_JETBRAINS_MONO_MEDIUM: return jetbrainsMonoMedium;
            case TypeConfig.FACE_NEWSREADER_72_SEMIBOLD: return newsreader72Semibold;
            case TypeConfig.FACE_NEWSREADER_16_REGULAR: return newsreader16Regular;
            case TypeConfig.FACE_NEWSREADER_16_ITALIC: return newsreader16Italic;
            case TypeConfig.FACE_TEXT_REGULAR:
            default:
                return textRegular;
        }
    }
}

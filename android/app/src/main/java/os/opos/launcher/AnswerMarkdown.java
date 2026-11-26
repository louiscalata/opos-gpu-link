package os.opos.launcher;

import android.graphics.Typeface;
import android.text.Spannable;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.TextPaint;
import android.text.style.LeadingMarginSpan;
import android.text.style.TypefaceSpan;

/** Converts the text-only parser's ranges to framework spans. */
final class AnswerMarkdown {
    private AnswerMarkdown() {}

    static CharSequence render(String raw, TextPaint paint, Typography typography) {
        AnswerMarkdownParser.Result parsed = AnswerMarkdownParser.parse(raw);
        SpannableStringBuilder styled = new SpannableStringBuilder(parsed.text);
        for (AnswerMarkdownParser.Mark mark : parsed.marks) {
            Object span;
            switch (MarkdownFace.forMark(mark.kind)) {
                case MarkdownFace.BOLD:
                    span = new TypefaceSpan(typography.face(
                            TypeConfig.emphasisFace(TypeConfig.body().face)));
                    break;
                case MarkdownFace.ITALIC:
                    span = new TypefaceSpan(typography.face(
                            TypeConfig.italicFace(TypeConfig.body().face)));
                    break;
                case MarkdownFace.MONOSPACE:
                    span = new TypefaceSpan(Typeface.MONOSPACE);
                    break;
                default:
                    continue;
            }
            styled.setSpan(span, mark.start, mark.end, Spannable.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        for (AnswerMarkdownParser.ListItem item : parsed.lists) {
            // Preserve a child's hierarchy when its text wraps on a narrow screen.
            float literalIndent = paint.measureText(item.prefix.substring(0, item.indent));
            float markerWidth = paint.measureText(item.prefix.substring(item.indent));
            AnswerMarkdownLayout.Margins margins = AnswerMarkdownLayout.list(
                    literalIndent, markerWidth, paint.measureText("    "), item.depth);
            styled.setSpan(new LeadingMarginSpan.Standard(margins.first, margins.rest),
                    item.start, item.end, Spanned.SPAN_PARAGRAPH);
        }
        int quoteIndent = AnswerMarkdownLayout.quote(paint.measureText("  "));
        for (AnswerMarkdownParser.Quote quote : parsed.quotes) {
            styled.setSpan(new LeadingMarginSpan.Standard(quoteIndent),
                    quote.start, quote.end, Spanned.SPAN_PARAGRAPH);
        }
        return styled;
    }
}

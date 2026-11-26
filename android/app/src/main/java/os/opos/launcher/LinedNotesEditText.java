package os.opos.launcher;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Rect;
import android.widget.EditText;

/** A phone-local notepad with faint hairline rules. */
final class LinedNotesEditText extends EditText {
    private final Paint rule = new Paint(Paint.ANTI_ALIAS_FLAG);

    LinedNotesEditText(Context context) {
        super(context);
        rule.setColor(context.getColor(R.color.notes_rule));
        rule.setStrokeWidth(Math.max(1f,
                context.getResources().getDisplayMetrics().density * 0.75f));
        setPadding(0, 8, 0, 0);
    }

    void setRuleColor(int color) {
        rule.setColor(color);
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        int lineHeight = getLineHeight();
        if (lineHeight > 0) {
            Rect bounds = new Rect();
            int lastRuleY = 0;
            for (int line = 0; line < getLineCount(); line++) {
                int baseline = getLineBounds(line, bounds);
                lastRuleY = NotesRulePosition.ruleY(baseline, bounds.bottom, lineHeight);
                canvas.drawLine(0, lastRuleY, getWidth(), lastRuleY, rule);
            }
            for (int y = lastRuleY + lineHeight;
                 NotesCompact.drawFillerRules(getText()) && y < getScrollY() + getHeight();
                 y += lineHeight) {
                canvas.drawLine(0, y, getWidth(), y, rule);
            }
        }
        super.onDraw(canvas);
    }
}

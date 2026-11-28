package os.opos.launcher;

import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.os.Build;
import android.text.SpannableStringBuilder;
import android.text.Spanned;
import android.text.TextPaint;
import android.text.TextUtils;
import android.text.style.ForegroundColorSpan;
import android.text.style.MetricAffectingSpan;
import android.util.TypedValue;
import android.view.WindowInsets;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

/**
 * The right-hand screen when the app spans both Surface Duo screens: heat, the USB link and one
 * block per answer lane. It only draws a {@link SpanStatsModel}; it owns no app state.
 */
final class SpanStatsView extends ScrollView {
    private static final float DIM_DOT_ALPHA = 0.35f;

    private static final class Row {
        final TextView name, state, work;

        Row(TextView name, TextView state, TextView work) {
            this.name = name;
            this.state = state;
            this.work = work;
        }
    }

    private final int basePaddingPx;
    private final LinearLayout column;
    private final List<Row> rows = new ArrayList<>();
    private Typography typography;
    private UiPalette palette;
    private String styleKey = "";
    private SpanStatsModel lastModel;
    private TextView kicker, heat, link;

    SpanStatsView(Context context) {
        super(context);
        basePaddingPx = Math.round(20f * context.getResources().getDisplayMetrics().density);
        column = new LinearLayout(context);
        column.setOrientation(LinearLayout.VERTICAL);
        column.setPadding(basePaddingPx, basePaddingPx, basePaddingPx, basePaddingPx);
        addView(column, new LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT));
        setFillViewport(true);
        setAccessibilityPaneTitle("Live stats");
        setOnApplyWindowInsetsListener((view, insets) -> {
            int top = 0;
            int bottom = 0;
            int right = 0;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                top = bars.top;
                bottom = bars.bottom;
                right = bars.right;
            }
            column.setPadding(basePaddingPx, basePaddingPx + top, basePaddingPx + right,
                    basePaddingPx + bottom);
            return insets;
        });
    }

    /** Safe to call again on a theme or type change; the next render redraws everything. */
    void style(Typography typography, UiPalette palette) {
        this.typography = typography;
        this.palette = palette;
        String key = palette.paper() + "|" + palette.ink() + "|" + palette.ok() + "|" + palette.error()
                + "|" + typography.bodySp();
        if (key.equals(styleKey) && kicker != null) return;
        styleKey = key;
        setBackgroundColor(Color.parseColor(palette.paper()));
        rebuild();
        if (lastModel != null) bind(lastModel);
    }

    void render(SpanStatsModel model) {
        if (model == null || typography == null || palette == null) return;
        if (model.sameAs(lastModel)) return;
        lastModel = model;
        bind(model);
    }

    private void rebuild() {
        column.removeAllViews();
        rows.clear();
        kicker = text(false);
        kicker.setText("Live stats");
        kicker.setTextColor(Color.parseColor(palette.label()));
        column.addView(kicker);
        heat = text(false);
        heat.setTypeface(typography.interSemibold);
        heat.setTextSize(TypedValue.COMPLEX_UNIT_SP, HeatMeter.TEXT_SP);
        heat.setPadding(0, dp(12), 0, 0);
        column.addView(heat);
        link = text(false);
        link.setTypeface(typography.interSemibold);
        link.setPadding(0, dp(4), 0, dp(8));
        column.addView(link);
    }

    private void bind(SpanStatsModel model) {
        String heatText = model.heatText();
        heat.setText(heatText);
        heat.setVisibility(TextUtils.isEmpty(heatText) ? GONE : VISIBLE);
        heat.setTextColor(Color.parseColor(palette.colorForTone(model.heatTone())));
        link.setText(model.linkText());
        link.setVisibility(TextUtils.isEmpty(model.linkText()) ? GONE : VISIBLE);
        link.setTextColor(Color.parseColor(palette.colorForTone(model.linkTone())));
        while (rows.size() > model.rowCount()) {
            Row gone = rows.remove(rows.size() - 1);
            column.removeView(gone.name);
            column.removeView(gone.state);
            column.removeView(gone.work);
        }
        while (rows.size() < model.rowCount()) addRow();
        for (int i = 0; i < rows.size(); i++) bindRow(rows.get(i), model, i);
    }

    private void addRow() {
        TextView name = text(false);
        name.setTextColor(Color.parseColor(palette.label()));
        name.setPadding(0, dp(12), 0, 0);
        TextView state = text(false);
        TextView work = text(true);
        work.setVisibility(GONE);
        column.addView(name);
        column.addView(state);
        column.addView(work);
        rows.add(new Row(name, state, work));
    }

    private void bindRow(Row row, SpanStatsModel model, int index) {
        row.name.setText(model.rowName(index));
        row.state.setText(model.rowState(index));
        row.state.setTextColor(Color.parseColor(palette.colorForTone(model.rowTone(index))));
        boolean working = model.rowWorking(index);
        row.work.setVisibility(working ? VISIBLE : GONE);
        if (working) {
            row.work.setTextColor(Color.parseColor(palette.ink()));
            row.work.setText(workingLine(model.rowWorkingLine(index), model.rowDotBright(index)));
        }
    }

    /** White (ink) line with a small green dot; the spinner bar uses the bundled mono face. */
    private CharSequence workingLine(String line, boolean dotBright) {
        SpannableStringBuilder styled = new SpannableStringBuilder(line);
        if (line.isEmpty()) return styled;
        int green = Color.parseColor(palette.ok());
        int alpha = dotBright ? 255 : Math.round(255 * DIM_DOT_ALPHA);
        styled.setSpan(new ForegroundColorSpan((green & 0x00FFFFFF) | (alpha << 24)),
                0, 1, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        if (line.length() > 2 && line.charAt(2) != ' ' && WorkingIndicator.SPINNER.indexOf(line.charAt(2)) >= 0) {
            styled.setSpan(new FaceSpan(typography.jetbrainsMonoMedium), 2, 3,
                    Spanned.SPAN_EXCLUSIVE_EXCLUSIVE);
        }
        return styled;
    }

    private TextView text(boolean working) {
        TextView view = new TextView(getContext());
        typography.state(view);
        if (working) {
            view.setIncludeFontPadding(false);
            view.setSingleLine(true);
            view.setEllipsize(TextUtils.TruncateAt.END);
            view.setPadding(0, dp(2), 0, dp(2));
            // The state line above already says "Streaming…" or "Thinking…" to TalkBack.
            view.setImportantForAccessibility(IMPORTANT_FOR_ACCESSIBILITY_NO);
        }
        return view;
    }

    private int dp(int value) {
        return Math.round(value * getResources().getDisplayMetrics().density);
    }

    private static final class FaceSpan extends MetricAffectingSpan {
        private final Typeface face;

        FaceSpan(Typeface face) {
            this.face = face;
        }

        @Override public void updateMeasureState(TextPaint paint) {
            paint.setTypeface(face);
        }

        @Override public void updateDrawState(TextPaint paint) {
            paint.setTypeface(face);
        }
    }
}

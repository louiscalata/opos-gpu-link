package os.opos.launcher;

import android.app.Activity;
import android.view.Gravity;
import android.view.View;
import android.widget.FrameLayout;

/**
 * Confines the page to the left Surface Duo screen and shows the stats pane on the right when the
 * window spans both screens. It only changes `screen`'s right margin and adds or removes one
 * sibling view; it never re-parents the page or recreates the activity.
 */
final class SpanLayoutController {
    private final Activity activity;
    private final FrameLayout root;
    private final View screen;
    private final FrameLayout.LayoutParams screenLp;
    private SpanStatsView statsView;
    private Typography typography;
    private UiPalette palette;
    private SpanGeometry lastGeometry = SpanGeometry.NONE;
    private int lastDensity = -1;
    private boolean spanned;

    SpanLayoutController(Activity activity, FrameLayout root, View screen) {
        this.activity = activity;
        this.root = root;
        this.screen = screen;
        this.screenLp = (FrameLayout.LayoutParams) screen.getLayoutParams();
    }

    boolean sync() {
        try {
            SpanGeometry g = HingeProbe.probe(activity);
            int d = HingeProbe.densityDpi(activity);
            if (g.equals(lastGeometry) && d == lastDensity) return false;
            lastGeometry = g;
            lastDensity = d;
            boolean sideBySide = SpanPolicy.resolve(g, d) == SpanPolicy.Mode.SIDE_BY_SIDE;
            if (sideBySide) {
                screenLp.rightMargin = Math.max(0, g.windowW - g.hingeLeft);
                screen.setLayoutParams(screenLp);
                ensureStatsView(g);
                if (statsView.getParent() == null) root.addView(statsView, new FrameLayout.LayoutParams(spanRightWidth(g, d), FrameLayout.LayoutParams.MATCH_PARENT, Gravity.END));
                spanned = true;
            } else {
                screenLp.rightMargin = 0;
                screen.setLayoutParams(screenLp);
                if (statsView != null && statsView.getParent() == root) root.removeView(statsView);
                spanned = false;
            }
            return true;
        } catch (RuntimeException e) {
            lastGeometry = SpanGeometry.NONE;
            lastDensity = -1;
            screenLp.rightMargin = 0;
            screen.setLayoutParams(screenLp);
            if (statsView != null && statsView.getParent() == root) root.removeView(statsView);
            spanned = false;
            return false;
        }
    }

    boolean spanned() { return spanned; }

    int contentWidthDp(int windowWidthDp) {
        return lastDensity < 0 ? windowWidthDp : SpanPolicy.contentWidthDp(lastGeometry, lastDensity, windowWidthDp);
    }

    void style(Typography typography, UiPalette palette) {
        this.typography = typography;
        this.palette = palette;
        if (statsView != null) statsView.style(typography, palette);
    }

    void update(SpanStatsModel model) {
        if (spanned && statsView != null) statsView.render(model);
    }

    private void ensureStatsView(SpanGeometry g) {
        if (statsView == null) {
            statsView = new SpanStatsView(activity);
            if (typography != null && palette != null) statsView.style(typography, palette);
        }
        statsView.setLayoutParams(new FrameLayout.LayoutParams(spanRightWidth(g, lastDensity), FrameLayout.LayoutParams.MATCH_PARENT, Gravity.END));
    }

    private int spanRightWidth(SpanGeometry g, int densityDpi) {
        return Math.max(0, SpanPaneMetrics.from(g).rightWidthPx);
    }
}

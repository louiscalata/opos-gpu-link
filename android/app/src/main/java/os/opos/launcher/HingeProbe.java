package os.opos.launcher;

import android.app.Activity;
import android.graphics.Rect;
import android.os.Build;
import android.util.Log;

import java.lang.reflect.Method;
import java.util.List;

/** Detects hinge geometry. */
final class HingeProbe {
    private static volatile SpanGeometry lastLoggedResult;

    private HingeProbe() {
    }

    static SpanGeometry probe(Activity activity) {
        SpanGeometry geometry = SpanGeometry.NONE;
        int windowW = 0;
        int windowH = 0;

        try {
            if (activity == null || Build.VERSION.SDK_INT < 30) {
                return logResult(SpanGeometry.NONE, "none");
            }

            Rect bounds = activity.getWindowManager().getCurrentWindowMetrics().getBounds();
            windowW = bounds.width();
            windowH = bounds.height();
            if (windowW <= 0 || windowH <= 0) {
                return logResult(SpanGeometry.NONE, "none");
            }

            if (activity.getPackageManager().hasSystemFeature("com.microsoft.device.display.displaymask")) {
                Object mask = Class.forName("com.microsoft.device.display.DisplayMask")
                        .getMethod("fromResourcesRectApproximation", android.content.Context.class)
                        .invoke(null, activity);
                @SuppressWarnings("unchecked")
                List<Rect> rects = (List<Rect>) mask.getClass()
                        .getMethod("getBoundingRectsForRotation", int.class)
                        .invoke(mask, (activity.getDisplay() == null ? 0 : activity.getDisplay().getRotation()));
                if (rects != null) {
                    for (Rect r : rects) {
                        if (r != null && !r.isEmpty()) {
                            Rect h = new Rect(r);
                            h.offset(-bounds.left, -bounds.top);
                            geometry = SpanGeometry.of(windowW, windowH, h.left, h.top, h.right, h.bottom);
                            if (SpanPolicy.verticalHinge(geometry)) {
                                return logResult(geometry, "primary");
                            }
                            break;
                        }
                    }
                }
            }
        } catch (Throwable ignored) {
            // Fall through to table.
        }

        geometry = DuoHingeTable.geometry(Build.MANUFACTURER, Build.MODEL, windowW, windowH);
        if (!SpanPolicy.verticalHinge(geometry)) {
            geometry = SpanGeometry.NONE;
        }
        return logResult(geometry, geometry == SpanGeometry.NONE ? "none" : "table");
    }

    static int densityDpi(Activity activity) {
        return activity.getResources().getConfiguration().densityDpi;
    }

    /** Logs only when the result changes; numbers and one word only, no device identifiers. */
    private static SpanGeometry logResult(SpanGeometry result, String kind) {
        if (lastLoggedResult == null || !lastLoggedResult.equals(result)) {
            if (result == SpanGeometry.NONE) {
                Log.d("OposSpan", "none");
            } else {
                Log.d("OposSpan", kind + " window " + result.windowW + "x" + result.windowH
                        + " hinge " + result.hingeLeft + "," + result.hingeTop + ","
                        + result.hingeRight + "," + result.hingeBottom);
            }
            lastLoggedResult = result;
        }
        return result;
    }
}

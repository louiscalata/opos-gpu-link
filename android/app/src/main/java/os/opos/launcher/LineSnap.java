package os.opos.launcher;

/** Pixel arithmetic for whole-line answer viewports and scroll positions. */
final class LineSnap {
    private LineSnap() {}

    static int viewportFor(int available, int lineHeight) {
        if (lineHeight <= 0) throw new IllegalArgumentException("lineHeight");
        return Math.max(0, available) / lineHeight * lineHeight;
    }

    static int snapTop(int scrollY, int[] lineTops) {
        if (lineTops == null || lineTops.length == 0 || scrollY <= 0) return 0;
        int low = 0;
        int high = lineTops.length - 1;
        while (low <= high) {
            int mid = (low + high) >>> 1;
            if (lineTops[mid] <= scrollY) low = mid + 1;
            else high = mid - 1;
        }
        return Math.max(0, lineTops[Math.max(0, high)]);
    }
}

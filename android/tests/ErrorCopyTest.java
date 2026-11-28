package os.opos.launcher;

public final class ErrorCopyTest {
    public static void main(String[] args) {
        String failed = "PC · 0 words · Could not finish on the PC. Try again.";
        String done = "Phone · 162 words · Done";
        String ready = "Phone · 0 words · Ready";
        check(ErrorCopy.errorLine(failed));
        check(ErrorCopy.errorLine("This model could not start."));
        check(ErrorCopy.errorLine("Garbled — Retry"));
        check(ErrorCopy.errorLine("Could not read answer · Retry"));
        check(ErrorCopy.errorLine("Granite 4.0 Micro 3B · 277 words · Stopped early. Here is what it wrote."));
        check(!ErrorCopy.errorLine("Nemotron Mini 4B · 9 words · Stopped"));
        check(!ErrorCopy.errorLine("Nemotron Mini 4B · 9 words · Stopped · 1.2 s"));
        check(ErrorCopy.errorLine("Nemotron Mini 4B · 9 words · Model stopped"));
        check(!ErrorCopy.errorLine(null));
        check(!ErrorCopy.errorLine(done));
        check(!ErrorCopy.errorLine(ready));
        check(!ErrorCopy.errorLine("Longest answer so far: LFM2 1.2B (314 words)"));
        String report = failed + "\n" + done + "\n" + "LFM2 1.2B · 314 words · Done";
        java.util.List<ErrorCopy.Range> ranges = ErrorCopy.lineRanges(report);
        if (ranges.size() != 3) throw new AssertionError("expected 3 ranges, got " + ranges.size());
        check(ranges.get(0).error);
        check(!ranges.get(1).error);
        check(!ranges.get(2).error);
        String mixedStops = "Nemotron Mini 4B · 9 words · Stopped\n"
                + "Granite 4.1 3B · 9 words · Stopped early. Here is what it wrote.";
        java.util.List<ErrorCopy.Range> stopRanges = ErrorCopy.lineRanges(mixedStops);
        check(!stopRanges.get(0).error);
        check(stopRanges.get(1).error);
        if (ranges.get(0).start != 0 || ranges.get(0).end != failed.length()) {
            throw new AssertionError("first range bounds");
        }
        if (ranges.get(1).start != failed.length() + 1) {
            throw new AssertionError("second range should skip the newline");
        }
        System.out.println("ErrorCopyTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
}

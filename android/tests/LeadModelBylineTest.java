package os.opos.launcher;

/** The lead card keeps its legacy byline until a negotiated model label arrives. */
public final class LeadModelBylineTest {
    public static void main(String[] args) {
        String label = "Small (fallback for Original)";
        equal("Small (fallback for Original) · Demo Mac · over USB",
                LeadModelByline.text("Demo Mac", label, "PC"));
        equal("Demo Mac · over USB", LeadModelByline.text("Demo Mac", null, "PC"));
        equal("Demo Mac · over USB", LeadModelByline.text("Demo Mac", "", "PC"));
        equal("Small (fallback for Original) · PC · over USB",
                LeadModelByline.text("", label, "PC"));
        equal("PC · over USB", LeadModelByline.text(null, null, "PC"));
        equal("Ordinateur · over USB", LeadModelByline.text("", "", "Ordinateur"));
        equal("Nemotron 3.5 Bolt · NVIDIA · M5 Pro MacBook Pro · over USB",
                LeadModelByline.text("M5 Pro MacBook Pro", "NVIDIA Nemotron 3.5 Bolt E4B 4GB", "computer"));
        equal("LFM2 1.2B (baseline) · Liquid AI · Demo Mac · over USB",
                LeadModelByline.text("Demo Mac", "LFM2 1.2B", "computer"));
        equal("Granite 4.1 3B · IBM · Demo Mac · over USB",
                LeadModelByline.text("Demo Mac", "IBM Granite 4.1 3B", "computer"));

        // Clearing the backend field immediately restores the same legacy text;
        // this formatter retains no label across snapshots or PC changes.
        equal("Small (fallback for Original) · Demo Mac · over USB",
                LeadModelByline.text("Demo Mac", label, "PC"));
        equal("Other PC · over USB", LeadModelByline.text("Other PC", null, "PC"));
        System.out.println("LeadModelBylineTest: OK");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

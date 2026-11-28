package os.opos.launcher;

/** The reported model names the card; the byline says where it runs. */
public final class LeadModelBylineTest {
    public static void main(String[] args) {
        equal("NVIDIA Nemotron 3.5 Bolt E4B 4GB", LeadModelByline.reportedModel(
                "NVIDIA Nemotron 3.5 Bolt E4B 4GB", "LFM2 1.2B", false));
        String answered = LeadModelByline.reportedModel(
                "NVIDIA Nemotron 3.5 Bolt E4B 4GB", "Liquid AI LFM2-1.2B", true);
        equal("Liquid AI LFM2-1.2B", answered);
        equal("LFM2 1.2B (baseline)", LeadModelByline.title("Older MacBook",
                answered, "Computer"));
        equal("Liquid AI · Older MacBook · over USB",
                LeadModelByline.text("Older MacBook", answered, "Computer"));
        equal("NVIDIA Nemotron 3.5 Bolt E4B 4GB", LeadModelByline.reportedModel(
                "NVIDIA Nemotron 3.5 Bolt E4B 4GB", "", true));
        equal("", LeadModelByline.reportedModel(null, "", true));
        check(!LeadModelByline.namedComputer("on the PC's GPU"));
        check(!LeadModelByline.namedComputer(" unknown "));
        check(LeadModelByline.namedComputer("M5 Pro MacBook Pro"));
        equal("Nemotron 3.5 Bolt", LeadModelByline.title("M5 Pro MacBook Pro",
                "NVIDIA Nemotron 3.5 Bolt E4B 4GB", "Computer"));
        equal("LFM2 1.2B (baseline)", LeadModelByline.title("Demo Mac",
                "Liquid AI LFM2-1.2B", "Computer"));
        equal("MacBook", LeadModelByline.title("M5 Pro MacBook Pro", null, "Computer"));
        equal("Mac", LeadModelByline.title("Demo Mac", "  ", "Computer"));
        equal("MacBook", LeadModelByline.title("", null, "MacBook"));
        equal("Computer", LeadModelByline.title(null, null, "Computer"));
        String label = "Small (fallback for Original)";
        equal("Small (fallback for Original)",
                LeadModelByline.title("Demo Mac", label, "Computer"));
        equal("Demo Mac · over USB",
                LeadModelByline.text("Demo Mac", label, "PC"));
        equal("Demo Mac · over USB", LeadModelByline.text("Demo Mac", null, "PC"));
        equal("Demo Mac · over USB", LeadModelByline.text("Demo Mac", "", "PC"));
        equal("PC · over USB",
                LeadModelByline.text("", label, "PC"));
        equal("PC · over USB", LeadModelByline.text(null, null, "PC"));
        equal("Ordinateur · over USB", LeadModelByline.text("", "", "Ordinateur"));
        equal("NVIDIA · M5 Pro MacBook Pro · over USB",
                LeadModelByline.text("M5 Pro MacBook Pro", "NVIDIA Nemotron 3.5 Bolt E4B 4GB", "computer"));
        equal("Liquid AI · Demo Mac · over USB",
                LeadModelByline.text("Demo Mac", "LFM2 1.2B", "computer"));
        equal("IBM · Demo Mac · over USB",
                LeadModelByline.text("Demo Mac", "IBM Granite 4.1 3B", "computer"));

        // Clearing the reported label returns to the computer title and place.
        equal("Mac", LeadModelByline.title("Demo Mac", null, "Computer"));
        equal("Demo Mac · over USB",
                LeadModelByline.text("Demo Mac", null, "PC"));
        equal("Other PC · over USB", LeadModelByline.text("Other PC", null, "PC"));
        System.out.println("LeadModelBylineTest: OK");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
}

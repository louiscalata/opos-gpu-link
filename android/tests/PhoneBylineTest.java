package os.opos.launcher;

public final class PhoneBylineTest {
    public static void main(String[] args) {
        equal("AceInstruct 1.5B · NVIDIA · on this phone", PhoneByline.text("NVIDIA AceInstruct 1.5B", "on this phone"));
        equal("Llama 3.2 3B · Meta · on this phone", PhoneByline.text("Meta Llama 3.2 3B", null));
        equal("Nemotron 3 Nano 4B · NVIDIA · on this phone", PhoneByline.text(" NVIDIA Nemotron 3 Nano 4B ", " "));
        equal("Granite 4.0 Micro 3B · IBM", PhoneByline.modelAndMaker("IBM Granite 4.0 Micro 3B"));
        equal("LFM2 1.2B · Liquid AI", PhoneByline.modelAndMaker("Liquid AI LFM2 1.2B"));
        // No known maker first: the name as given.
        equal("AceInstruct 1.5B · on this phone", PhoneByline.text("AceInstruct 1.5B", "on this phone"));
        equal("NVIDIAX 2B", PhoneByline.modelAndMaker("NVIDIAX 2B"));
        equal("NVIDIA", PhoneByline.modelAndMaker("NVIDIA"));
        // No model known: only the place.
        equal("on this phone", PhoneByline.text("", "on this phone"));
        equal("on this phone", PhoneByline.text(null, null));
        System.out.println("PhoneBylineTest: OK");
    }

    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected <" + expected + "> but was <" + actual + ">");
        }
    }
}

package os.opos.launcher;

public final class ModelDisplayTest {
    public static void main(String[] args) {
        equal("Nemotron 3.5 Bolt", ModelDisplay.label("NVIDIA Nemotron 3.5 Bolt E4B 4GB"));
        equal("Nemotron 3.5 Bolt", ModelDisplay.label("Nemotron-3.5-Bolt-E4B"));
        equal("Nemotron 3.5 Bolt", ModelDisplay.label("NVIDIA_Nemotron-3.5-Bolt-E4B"));
        equal("LFM2 1.2B (baseline)", ModelDisplay.label("Liquid AI LFM2-1.2B"));
        equal("LFM2 1.2B (baseline)", ModelDisplay.label("LFM2 1.2B (baseline)"));
        equal("LFM2 (baseline)", ModelDisplay.label("LFM2"));
        equal("LFM2 2.6B (baseline)", ModelDisplay.label("LiquidAI_LFM2-2.6B"));
        equal("LFM2 1.2B (baseline)", ModelDisplay.label("LiquidAI_LFM2-1.2B"));
        equal("Qwen3.5-2B", ModelDisplay.label(" Qwen3.5-2B "));
        equal("Qwen3.5-2B", ModelDisplay.label("Alibaba Qwen3.5-2B"));
        equal("Granite 4.1 3B", ModelDisplay.label("Granite 4.1 3B"));
        equal("Granite 4.1 3B", ModelDisplay.label("IBM Granite 4.1 3B"));
        equal("Granite 4.1 3B", ModelDisplay.firstNonBlank("   ", "Granite 4.1 3B"));
        equal("Qwen3.5-2B", ModelDisplay.firstNonBlank(null, " Qwen3.5-2B "));
        // The shipped companion still lists these as fallbacks; never silently rename them.
        equal("Nemotron Mini 4B", ModelDisplay.label("Nemotron Mini 4B"));
        equal("Qwen2.5 1.5B", ModelDisplay.label("Qwen2.5 1.5B"));
        equal("Granite 4.0 Micro 3B", ModelDisplay.label("Granite 4.0 Micro 3B"));
        System.out.println("ModelDisplayTest OK");
    }

    private static void equal(String expected, String actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError("expected <" + expected + "> but was <" + actual + ">");
        }
    }
}

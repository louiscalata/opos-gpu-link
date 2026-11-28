package os.opos.launcher;

public final class ModelMakerTest {
    public static void main(String[] args) {
        equal("NVIDIA", ModelMaker.maker("", "Nemotron-3.5-Bolt-E4B"));
        equal("NVIDIA", ModelMaker.maker(null, "NVIDIA AceInstruct 1.5B"));
        equal("NVIDIA", ModelMaker.maker("", "NVIDIA"));
        equal("Liquid AI", ModelMaker.maker("Liquid AI", "LFM2 1.2B (baseline)"));
        equal("Liquid AI", ModelMaker.maker("", "LFM2 1.2B"));
        equal("Qwen (Alibaba)", ModelMaker.maker("Qwen", "Qwen3.5-2B"));
        equal("Qwen (Alibaba)", ModelMaker.maker("", "Qwen3.5-2B"));
        equal("IBM", ModelMaker.maker("", "Granite 4.1 3B"));
        equal("", ModelMaker.maker("", "Some Other 3B"));
        equal("NVIDIA AceInstruct 1.5B · on this phone",
                ModelMaker.details("NVIDIA AceInstruct 1.5B", "NVIDIA", "on this phone"));
        equal("Nemotron 3.5 Bolt · NVIDIA · M5 Pro MacBook Pro",
                ModelMaker.details("Nemotron-3.5-Bolt-E4B", "NVIDIA", "M5 Pro MacBook Pro"));
        equal("LFM2 1.2B (baseline) · Liquid AI · on this phone",
                ModelMaker.details("LFM2-1.2B", "Liquid AI", "on this phone"));
        equal("Some Other 3B · on this phone", ModelMaker.details("Some Other 3B", "", "on this phone"));
        equal("NVIDIA · on this phone", ModelMaker.details("", "NVIDIA", "on this phone"));
        equal("on this phone", ModelMaker.details("", "", "on this phone"));
        check(!ModelMaker.details("X", "", "y").contains("unavailable"), "never Maker unavailable");
        System.out.println("ModelMakerTest OK");
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError("expected <" + expected + "> but was <" + actual + ">");
        }
    }

    private static void check(boolean ok, String message) {
        if (!ok) throw new AssertionError(message);
    }
}

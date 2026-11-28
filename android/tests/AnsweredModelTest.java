package os.opos.launcher;

public final class AnsweredModelTest {
    public static void main(String[] args) {
        // The slot now holds Nemotron, but the saved answer was written by Qwen.
        equal("Qwen2.5 1.5B", AnsweredModel.label("Nemotron 3 Nano 4B", "Qwen2.5 1.5B"));
        equal("", AnsweredModel.maker("Nemotron 3 Nano 4B", "NVIDIA", "Qwen2.5 1.5B"));
        // Same model: keep the slot's maker.
        equal("Qwen2.5 1.5B", AnsweredModel.label("Qwen2.5 1.5B", "Qwen2.5 1.5B"));
        equal("Alibaba", AnsweredModel.maker("Qwen2.5 1.5B", "Alibaba", " Qwen2.5 1.5B "));
        // No answer yet (or an answer without a model): the slot names the card.
        equal("Nemotron 3 Nano 4B", AnsweredModel.label("Nemotron 3 Nano 4B", ""));
        equal("Nemotron 3 Nano 4B", AnsweredModel.label("Nemotron 3 Nano 4B", null));
        equal("NVIDIA", AnsweredModel.maker("Nemotron 3 Nano 4B", "NVIDIA", null));
        equal("", AnsweredModel.label(null, null));
        equal("Nemotron 3 Nano 4B", AnsweredModel.label(" Nemotron 3 Nano 4B ", "   "));
        equal("NVIDIA", AnsweredModel.maker("Nemotron 3 Nano 4B", " NVIDIA ", " "));
        equal("NVIDIA", AnsweredModel.maker(" Nemotron 3 Nano 4B ", "NVIDIA", "Nemotron 3 Nano 4B"));
        equal("Meta", ModelMaker.maker(AnsweredModel.maker(
                "Meta Llama 3.2 3B", "Meta", "Meta Llama 3.2 3B"), "Meta Llama 3.2 3B"));
        equal("", AnsweredModel.maker(null, null, "Qwen2.5 1.5B"));
        System.out.println("AnsweredModelTest: OK");
    }

    private static void equal(Object expected, Object actual) {
        if (expected == null ? actual != null : !expected.equals(actual)) {
            throw new AssertionError("expected <" + expected + "> but was <" + actual + ">");
        }
    }
}

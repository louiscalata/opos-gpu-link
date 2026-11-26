package os.opos.launcher;

public final class PhoneModelGateTest {
    public static void main(String[] args) {
        check(PhoneModelGate.hidden("Qwen3 4B"));
        check(PhoneModelGate.hidden("qwen3-4b"));
        check(PhoneModelGate.hidden("qwen/qwen3-4b"));
        check(PhoneModelGate.hidden("Qwen3-4B-Instruct"));
        check(!PhoneModelGate.hidden("Qwen2.5 1.5B"));
        check(!PhoneModelGate.hidden("qwen2.5-1.5b"));
        check(!PhoneModelGate.hidden("Qwen3.8 27B"));
        check(!PhoneModelGate.hidden("qwen3.8-27b"));
        check(!PhoneModelGate.hidden("LFM2 1.2B"));
        check(!PhoneModelGate.hidden("Granite 4.0 Micro 3B"));
        check(!PhoneModelGate.hidden("AceInstruct 1.5B"));
        check(!PhoneModelGate.hidden("SmolLM2 1.7B"));
        check(!PhoneModelGate.hidden("LFM3 1.7B"));
        check(!PhoneModelGate.hidden((String) null));
        check(!PhoneModelGate.hidden(""));
        check(PhoneModelGate.hidden("Muse Glimmer 30B"));
        check(PhoneModelGate.hidden("muse-glimmer-30b"));
        System.out.println("PhoneModelGateTest: OK");
    }

    private static void check(boolean value) {
        if (!value) throw new AssertionError();
    }
}

package os.opos.launcher;

import java.nio.file.Files;
import java.nio.file.Path;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

/** Host-side checks for both failed panes with and without partial text. */
public final class AnswerFailureLabelTest {
    public static void main(String[] args) throws Exception {
        equal(R.string.phone_failed_partial, AnswerFailureLabel.resource(false, "partial"));
        equal(R.string.gpu_failed_partial, AnswerFailureLabel.resource(true, "partial"));
        equal(R.string.phone_failed, AnswerFailureLabel.resource(false, ""));
        equal(R.string.gpu_failed, AnswerFailureLabel.resource(true, ""));
        equal(R.string.phone_failed, AnswerFailureLabel.resource(false, null));
        equal(R.string.gpu_failed, AnswerFailureLabel.resource(true, null));
        equal(R.string.phone_failed, AnswerFailureLabel.resource(false, " \n "));
        equal(R.string.gpu_failed, AnswerFailureLabel.resource(true, " \n "));
        equal(R.string.answer_garbled, AnswerFailureLabel.resource(false, "partial", "garbled"));
        equal(R.string.answer_garbled, AnswerFailureLabel.resource(true, "", "garbled"));
        equal(R.string.answer_garbled, AnswerFailureLabel.resource(false, null, "garbled"));
        equal(R.string.gpu_failed_partial,
                AnswerFailureLabel.resource(true, "partial", "stream_error"));

        Document strings = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(
                Files.newInputStream(Path.of("app/src/main/res/values/strings.xml")));
        equal("Stopped early. Here is what it wrote.", string(strings, "phone_failed_partial"));
        equal("Stopped early. Here is what it sent.", string(strings, "gpu_failed_partial"));
        equal("Could not finish on this phone. Try again.", string(strings, "phone_failed"));
        equal("Could not finish on the PC. Try again.", string(strings, "gpu_failed"));
        equal("Garbled — Retry", string(strings, "answer_garbled"));
        System.out.println("AnswerFailureLabelTest: OK");
    }

    private static String string(Document document, String name) {
        NodeList nodes = document.getElementsByTagName("string");
        for (int i = 0; i < nodes.getLength(); i++) {
            Element element = (Element) nodes.item(i);
            if (name.equals(element.getAttribute("name"))) return element.getTextContent();
        }
        throw new AssertionError("Missing string resource: " + name);
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError("Expected " + expected + " but got " + actual);
        }
    }
}

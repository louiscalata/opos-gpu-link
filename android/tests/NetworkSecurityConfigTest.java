package os.opos.launcher;

import java.nio.file.Path;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

/** The app may use cleartext only to 127.0.0.1 and must not trust public HTTPS CAs. */
public final class NetworkSecurityConfigTest {
    public static void main(String[] args) throws Exception {
        Document document = xml();
        Element root = document.getDocumentElement();
        equal("network-security-config", root.getTagName(), "root element");

        NodeList bases = document.getElementsByTagName("base-config");
        equal(1, bases.getLength(), "one base-config");
        Element base = (Element) bases.item(0);
        equal("false", base.getAttribute("cleartextTrafficPermitted"), "base cleartext off");
        NodeList anchors = base.getElementsByTagName("trust-anchors");
        equal(1, anchors.getLength(), "base-config declares trust-anchors");
        equal(0, ((Element) anchors.item(0)).getElementsByTagName("certificates").getLength(),
                "no public or user CA certificates, so HTTPS to the internet fails");

        NodeList domains = document.getElementsByTagName("domain-config");
        equal(1, domains.getLength(), "one domain-config");
        Element domainConfig = (Element) domains.item(0);
        equal("true", domainConfig.getAttribute("cleartextTrafficPermitted"),
                "loopback cleartext allowed");
        NodeList domainTags = domainConfig.getElementsByTagName("domain");
        equal(1, domainTags.getLength(), "only 127.0.0.1");
        Element domain = (Element) domainTags.item(0);
        equal("127.0.0.1", domain.getTextContent().trim(), "loopback only");
        equal("false", domain.getAttribute("includeSubdomains"), "no subdomain wildcard");

        System.out.println("NetworkSecurityConfigTest: OK");
    }

    private static Document xml() throws Exception {
        DocumentBuilderFactory factory = DocumentBuilderFactory.newInstance();
        factory.setFeature("http://apache.org/xml/features/disallow-doctype-decl", true);
        Path path = Path.of("app/src/main/res/xml/network_security_config.xml");
        return factory.newDocumentBuilder().parse(path.toFile());
    }

    private static void equal(String expected, String actual, String label) {
        if (!expected.equals(actual)) {
            throw new AssertionError(label + ": expected " + expected + " but was " + actual);
        }
    }

    private static void equal(int expected, int actual, String label) {
        if (expected != actual) {
            throw new AssertionError(label + ": expected " + expected + " but was " + actual);
        }
    }
}

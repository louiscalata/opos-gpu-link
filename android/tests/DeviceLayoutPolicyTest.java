package os.opos.launcher;

import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.nio.file.Path;
import javax.xml.parsers.DocumentBuilderFactory;
import org.w3c.dom.Document;
import org.w3c.dom.Element;
import org.w3c.dom.NodeList;

public final class DeviceLayoutPolicyTest {
    public static void main(String[] args) throws Exception {
        eq(1, DeviceLayoutPolicy.columns(360, false, 4));
        eq(1, DeviceLayoutPolicy.columns(374, true, 4));
        eq(1, DeviceLayoutPolicy.columns(880, false, 1));
        eq(2, DeviceLayoutPolicy.columns(600, false, 2));
        eq(2, DeviceLayoutPolicy.columns(880, false, 4));
        eq(2, DeviceLayoutPolicy.columns(880, false, 2));
        eq(DeviceLayoutPolicy.Side.PHONE, DeviceLayoutPolicy.side("phone", ""));
        eq(DeviceLayoutPolicy.Side.PHONE, DeviceLayoutPolicy.side("m1", "phone"));
        eq(DeviceLayoutPolicy.Side.PHONE, DeviceLayoutPolicy.side("m4", ""));
        eq(DeviceLayoutPolicy.Side.COMPUTER, DeviceLayoutPolicy.side("gpu", ""));
        eq(DeviceLayoutPolicy.Side.COMPUTER, DeviceLayoutPolicy.side("g1", "pc"));
        eq(DeviceLayoutPolicy.Side.UNKNOWN, DeviceLayoutPolicy.side("other", ""));
        eq(DeviceLayoutPolicy.Side.PHONE,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.PHONE, 0, 1));
        eq(DeviceLayoutPolicy.Side.COMPUTER,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.COMPUTER, 1, 0));
        eq(DeviceLayoutPolicy.Side.PHONE,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.PHONE, 1, 0));
        eq(DeviceLayoutPolicy.Side.PHONE,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.PHONE, 3, 1));
        eq(DeviceLayoutPolicy.Side.PHONE,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.PHONE, 2, 1));
        eq(DeviceLayoutPolicy.Side.COMPUTER,
                DeviceLayoutPolicy.column(DeviceLayoutPolicy.Side.COMPUTER, 0, 3));
        eq(Arrays.asList("gpu", "phone", "m1", "m4"), DeviceLayoutPolicy.orderedPanes(
                Arrays.asList("phone", "m1", "gpu", "m4"), new HashMap<>()));
        eq(Arrays.asList("gpu", "phone", "m1", "m2", "m3", "m4", "g1"),
                DeviceLayoutPolicy.orderedPanes(
                        Arrays.asList("gpu", "phone", "m1", "m2", "m3", "m4", "g1"),
                        Collections.emptyMap()));
        eq(Arrays.asList("gpu", "m1", "m2", "m3", "m4"), DeviceLayoutPolicy.orderedPanes(
                Arrays.asList("m1", "gpu", "m2", "m3", "m4"), Collections.emptyMap()));
        eq(Arrays.asList("gpu", "phone"), DeviceLayoutPolicy.orderedPanes(
                Arrays.asList("phone", "gpu"), Collections.emptyMap()));
        eq(DeviceLayoutPolicy.LinkState.CABLE_OUT,
                DeviceLayoutPolicy.linkState(false, true, false, true));
        eq(DeviceLayoutPolicy.LinkState.PAUSED,
                DeviceLayoutPolicy.linkState(true, false, true, false));
        eq(DeviceLayoutPolicy.LinkState.ERROR,
                DeviceLayoutPolicy.linkState(true, false, false, true));
        eq(DeviceLayoutPolicy.LinkState.ERROR,
                DeviceLayoutPolicy.linkState(true, false, true, true));
        eq(DeviceLayoutPolicy.LinkState.CONNECTED,
                DeviceLayoutPolicy.linkState(true, true, false, false));
        eq(DeviceLayoutPolicy.LinkState.WAITING,
                DeviceLayoutPolicy.linkState(null, true, false, false));
        eq("Phone connected to MacBook Pro by USB-C",
                DeviceLayoutPolicy.description("MacBook Pro", DeviceLayoutPolicy.LinkState.CONNECTED));
        eq("Galaxy Z Flip 6", DeviceLayoutPolicy.phoneName(" Galaxy Z Flip 6 ", "SM-F741U"));
        eq("Galaxy Z Flip 6", DeviceLayoutPolicy.phoneName("", "SM-F741U"));
        eq("Pixel", DeviceLayoutPolicy.phoneName("", "Pixel"));
        eq("Phone", DeviceLayoutPolicy.phoneName(null, null));
        eq("Galaxy Z Flip 6 connected to MacBook Pro by USB-C",
                DeviceLayoutPolicy.description("Galaxy Z Flip 6", "MacBook Pro",
                        DeviceLayoutPolicy.LinkState.CONNECTED));
        Document layout = DocumentBuilderFactory.newInstance().newDocumentBuilder().parse(
                Path.of("app/src/main/res/layout/models.xml").toFile());
        eq("wrap_content", height(layout, "device_band"));
        eq("wrap_content", height(layout, "device_phone"));
        eq("wrap_content", height(layout, "device_computer"));
        System.out.println("DeviceLayoutPolicyTest: OK");
    }

    private static String height(Document layout, String id) {
        NodeList nodes = layout.getElementsByTagName("LinearLayout");
        for (int i = 0; i < nodes.getLength(); i++) {
            Element element = (Element) nodes.item(i);
            if (("@+id/" + id).equals(element.getAttribute("android:id"))) {
                return element.getAttribute("android:layout_height");
            }
        }
        throw new AssertionError("Missing layout id: " + id);
    }

    private static void eq(Object expected, Object actual) {
        if (!expected.equals(actual)) throw new AssertionError(expected + " != " + actual);
    }
}

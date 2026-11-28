package os.opos.launcher;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/** Keep Java calls in the Android app usable on its minimum API level. */
public final class Api29AuditTest {
    // Optional use needs a typed check before its newer isEmpty method can be allowed safely.
    private static final Pattern LATER_JAVA_API = Pattern.compile(
            "\\b(?:List|Set|Map)\\s*\\.\\s*(?:of|ofEntries|entry|copyOf)\\s*\\("
                    + "|\\bFiles\\s*\\.\\s*(?:readString|writeString)\\s*\\("
                    + "|\\bPath\\s*\\.\\s*of\\s*\\("
                    + "|\\bObjects\\s*\\.\\s*(?:requireNonNullElse|requireNonNullElseGet|checkIndex|checkFromToIndex|checkFromIndexSize)\\s*\\("
                    + "|\\.\\s*(?:isBlank|strip|stripLeading|stripTrailing|stripIndent|repeat|lines|toList|formatted|indent|transform|translateEscapes|readAllBytes|transferTo)\\s*\\("
                    + "|\\bOptional(?:Int|Long|Double)?\\b");

    public static void main(String[] args) throws IOException {
        blocked("List.of(\"x\")");
        blocked("Set.copyOf(values)");
        blocked("Map.entry(key, value)");
        blocked("List.copyOf(values)");
        blocked("text.isBlank()");
        blocked("\"text\".strip()");
        blocked("text.lines()");
        blocked("text.repeat(2)");
        blocked("stream.toList()");
        blocked("Optional<String> value");
        blocked("Files.readString(path)");
        blocked("Path.of(name)");
        allowed("LeadingWhitespace.strip(line)");
        allowed("text.isEmpty()");
        allowed("// List.of(1)\nString note = \"text.isBlank()\";");
        allowed("/* Set.of(1) */ String text = \"a//b\";");

        Path root = Path.of("app/src/main/java");
        if (!Files.isDirectory(root)) throw new AssertionError("Missing Android main sources: " + root);
        List<String> hits = new ArrayList<>();
        try (Stream<Path> files = Files.walk(root)) {
            for (Path file : (Iterable<Path>) files.filter(p -> p.toString().endsWith(".java"))::iterator) {
                String source = Files.readString(file);
                String code = codeOnly(source);
                Matcher match = LATER_JAVA_API.matcher(code);
                while (match.find()) {
                    if (localStrip(code, match)) continue;
                    long line = 1 + source.substring(0, match.start()).chars().filter(c -> c == '\n').count();
                    hits.add(file + ":" + line + " " + match.group());
                }
            }
        }
        if (!hits.isEmpty()) throw new AssertionError("Java calls need API 29 replacements: " + hits);
        System.out.println("Api29AuditTest: OK");
    }

    private static void blocked(String source) {
        if (firstUnsupported(source) == null) throw new AssertionError("Audit missed: " + source);
    }

    private static void allowed(String source) {
        if (firstUnsupported(source) != null) throw new AssertionError("Audit flagged safe code: " + source);
    }

    private static String firstUnsupported(String source) {
        String code = codeOnly(source);
        Matcher match = LATER_JAVA_API.matcher(code);
        while (match.find()) {
            if (!localStrip(code, match)) return match.group();
        }
        return null;
    }

    private static boolean localStrip(String code, Matcher match) {
        if (!match.group().matches("\\.\\s*strip\\s*\\(")) return false;
        // The app's LeadingWhitespace.strip helper is unrelated to String.strip.
        int end = match.start();
        while (end > 0 && Character.isWhitespace(code.charAt(end - 1))) end--;
        int start = end;
        while (start > 0 && Character.isJavaIdentifierPart(code.charAt(start - 1))) start--;
        return code.substring(start, end).equals("LeadingWhitespace");
    }

    /** Hide comments and literals without shifting call positions or line numbers. */
    private static String codeOnly(String source) {
        StringBuilder code = new StringBuilder(source.length());
        int state = 0; // 0 code, 1 line comment, 2 block comment, 3 string, 4 character
        for (int i = 0; i < source.length(); i++) {
            char c = source.charAt(i);
            char next = i + 1 < source.length() ? source.charAt(i + 1) : 0;
            if (state == 0) {
                if (c == '/' && next == '/') {
                    code.append("  ");
                    i++;
                    state = 1;
                } else if (c == '/' && next == '*') {
                    code.append("  ");
                    i++;
                    state = 2;
                } else if (c == '"' || c == '\'') {
                    code.append(' ');
                    state = c == '"' ? 3 : 4;
                } else {
                    code.append(c);
                }
            } else if (state == 1) {
                code.append(c == '\n' ? '\n' : ' ');
                if (c == '\n') state = 0;
            } else if (state == 2) {
                if (c == '*' && next == '/') {
                    code.append("  ");
                    i++;
                    state = 0;
                } else {
                    code.append(c == '\n' ? '\n' : ' ');
                }
            } else if (c == '\\' && next != 0) {
                code.append("  ");
                i++;
            } else {
                code.append(c == '\n' ? '\n' : ' ');
                if ((state == 3 && c == '"') || (state == 4 && c == '\'')) state = 0;
            }
        }
        return code.toString();
    }
}

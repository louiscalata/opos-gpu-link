package os.opos.launcher;

import java.util.ArrayList;
import java.util.List;

/** A deliberately small, text-only Markdown parser for model answers. */
final class AnswerMarkdownParser {
    static final int BOLD = 1;
    static final int ITALIC = 2;
    static final int CODE = 3;
    private static final int MAX_NESTING = 8;

    static final class Mark {
        final int start;
        final int end;
        final int kind;

        Mark(int start, int end, int kind) {
            this.start = start;
            this.end = end;
            this.kind = kind;
        }
    }

    static final class ListItem {
        final int start;
        final int end;
        final String prefix;
        final int depth;
        final int indent;

        ListItem(int start, int end, String prefix, int indent, int depth) {
            this.start = start;
            this.end = end;
            this.prefix = prefix;
            this.indent = indent;
            this.depth = depth;
        }
    }

    static final class Quote {
        final int start;
        final int end;

        Quote(int start, int end) {
            this.start = start;
            this.end = end;
        }
    }

    static final class Result {
        final String text;
        final List<Mark> marks;
        final List<ListItem> lists;
        final List<Quote> quotes;

        Result(String text, List<Mark> marks, List<ListItem> lists, List<Quote> quotes) {
            this.text = text;
            this.marks = marks;
            this.lists = lists;
            this.quotes = quotes;
        }
    }

    private static final class LineFormat {
        final boolean heading;
        final boolean tableHeader;
        final boolean code;
        final boolean quote;
        final String listPrefix;
        final int listIndent;
        final int listDepth;
        final int blockStart;

        LineFormat(boolean heading, boolean tableHeader, boolean code, boolean quote,
                   String listPrefix, int listIndent, int listDepth, int blockStart) {
            this.heading = heading;
            this.tableHeader = tableHeader;
            this.code = code;
            this.quote = quote;
            this.listPrefix = listPrefix;
            this.listIndent = listIndent;
            this.listDepth = listDepth;
            this.blockStart = blockStart;
        }
    }

    private AnswerMarkdownParser() {}

    static Result parse(String raw) {
        String source = (raw == null ? "" : raw).replace("\r\n", "\n").replace('\r', '\n');
        StringBuilder blockText = new StringBuilder(source.length());
        List<LineFormat> lines = new ArrayList<>();
        String[] sourceLines = source.split("\n", -1);
        boolean previousNestedOrNumbered = false;
        char fence = 0;
        int fenceWidth = 0;
        int tableColumns = 0;
        for (int lineIndex = 0; lineIndex < sourceLines.length; lineIndex++) {
            String line = sourceLines[lineIndex];
            if (fence != 0) {
                if (fenceLength(line, fence, fenceWidth, true) > 0) {
                    fence = 0;
                    fenceWidth = 0;
                } else {
                    addLine(blockText, lines, line, false, false, true, false,
                            null, 0, 0);
                }
                previousNestedOrNumbered = false;
                continue;
            }
            int openingWidth = fenceLength(line, (char) 0, 3, false);
            if (openingWidth > 0) {
                fence = line.stripLeading().charAt(0);
                fenceWidth = openingWidth;
                tableColumns = 0;
                previousNestedOrNumbered = false;
                continue;
            }
            if (isHorizontalRule(line)) {
                addLine(blockText, lines, "", false, false, false, false,
                        null, 0, 0);
                tableColumns = 0;
                previousNestedOrNumbered = false;
                continue;
            }
            List<String> cells = tableCells(line);
            if (tableColumns > 0) {
                if (cells != null && cells.size() == tableColumns) {
                    addLine(blockText, lines, String.join("  ·  ", cells), false,
                            false, false, false, null, 0, 0);
                    previousNestedOrNumbered = false;
                    continue;
                }
                tableColumns = 0;
            }
            if (cells != null && lineIndex + 1 < sourceLines.length
                    && isTableSeparator(sourceLines[lineIndex + 1], cells.size())) {
                addLine(blockText, lines, String.join("  ·  ", cells), false,
                        true, false, false, null, 0, 0);
                tableColumns = cells.size();
                previousNestedOrNumbered = false;
                lineIndex++;
                continue;
            }
            boolean quote = line.startsWith("> ");
            if (quote) line = line.substring(2);
            int bodyStart = 0;
            boolean heading = false;
            String listPrefix = null;
            int listIndent = 0;
            int listDepth = 0;
            boolean numbered = false;

            int hashes = 0;
            if (!quote) {
                while (hashes < line.length() && hashes < 6 && line.charAt(hashes) == '#') {
                    hashes++;
                }
                if (hashes > 0 && hashes < line.length() && line.charAt(hashes) == ' ') {
                    heading = true;
                    bodyStart = hashes + 1;
                } else {
                    int indent = 0;
                    while (indent < line.length() && line.charAt(indent) == ' ') {
                        indent++;
                    }
                    if (indent <= 4) {
                        int markerEnd = indent;
                        boolean bullet = false;
                        if (markerEnd < line.length()
                                && (line.charAt(markerEnd) == '-'
                                || line.charAt(markerEnd) == '*'
                                || line.charAt(markerEnd) == '+')) {
                            bullet = true;
                            markerEnd++;
                        } else {
                            while (markerEnd < line.length()
                                    && Character.isDigit(line.charAt(markerEnd))) {
                                markerEnd++;
                            }
                            if (markerEnd > indent && markerEnd < line.length()
                                    && (line.charAt(markerEnd) == '.'
                                    || line.charAt(markerEnd) == ')')) {
                                markerEnd++;
                            } else {
                                markerEnd = indent;
                            }
                        }
                        if ((indent != 1 || bullet) && markerEnd > indent
                                && markerEnd < line.length()
                                && isListSpace(line.charAt(markerEnd))) {
                            bodyStart = markerEnd + 1;
                            while (bodyStart < line.length()
                                    && isListSpace(line.charAt(bodyStart))) {
                                bodyStart++;
                            }
                            listPrefix = line.substring(0, indent)
                                    + (bullet ? "• " : line.substring(indent, markerEnd) + " ");
                            listIndent = indent;
                            listDepth = bullet && indent >= 1 && indent <= 3
                                    ? (previousNestedOrNumbered ? 1 : 0) : indent / 2;
                            numbered = !bullet;
                        }
                    }
                }
            }

            addLine(blockText, lines, (listPrefix == null ? "" : listPrefix)
                    + line.substring(bodyStart), heading, false, false, quote,
                    listPrefix, listIndent, listDepth);
            previousNestedOrNumbered = listPrefix != null && (numbered || listDepth > 0);
        }

        // Inline markers can span lines; block prefixes cannot. Parsing the joined
        // text also lets a streamed opening marker become styled when it closes.
        // Fenced code segments bypass inline parsing entirely.
        StringBuilder text = new StringBuilder(blockText.length());
        List<Mark> marks = new ArrayList<>();
        List<ListItem> lists = new ArrayList<>();
        List<Quote> quotes = new ArrayList<>();
        String joined = blockText.toString();
        if (!lines.isEmpty()) {
            int segmentStart = 0;
            boolean code = lines.get(0).code;
            for (int i = 1; i <= lines.size(); i++) {
                if (i < lines.size() && lines.get(i).code == code) continue;
                int segmentEnd = i == lines.size() ? joined.length() : lines.get(i).blockStart;
                if (code) {
                    int start = text.length();
                    text.append(joined, segmentStart, segmentEnd);
                    if (text.length() > start) marks.add(new Mark(start, text.length(), CODE));
                } else {
                    appendInline(joined, segmentStart, segmentEnd, text, marks, 0);
                }
                if (i < lines.size()) {
                    segmentStart = segmentEnd;
                    code = lines.get(i).code;
                }
            }
        }
        int renderedStart = 0;
        for (LineFormat format : lines) {
            int newline = text.indexOf("\n", renderedStart);
            int renderedEnd = newline < 0 ? text.length() : newline;
            if ((format.heading || format.tableHeader) && renderedEnd > renderedStart) {
                marks.add(new Mark(renderedStart, renderedEnd, BOLD));
            }
            int paragraphEnd = newline < 0 ? renderedEnd : newline + 1;
            if (format.listPrefix != null) {
                if (paragraphEnd > renderedStart) {
                    lists.add(new ListItem(renderedStart, paragraphEnd,
                                           format.listPrefix, format.listIndent,
                                           format.listDepth));
                }
            }
            if (format.quote && paragraphEnd > renderedStart) {
                quotes.add(new Quote(renderedStart, paragraphEnd));
            }
            if (newline < 0) break;
            renderedStart = newline + 1;
        }
        return new Result(text.toString(), marks, lists, quotes);
    }

    private static void addLine(StringBuilder text, List<LineFormat> lines, String body,
                                boolean heading, boolean tableHeader, boolean code,
                                boolean quote, String listPrefix, int listIndent,
                                int listDepth) {
        if (!lines.isEmpty()) text.append('\n');
        int start = text.length();
        text.append(body);
        lines.add(new LineFormat(heading, tableHeader, code, quote, listPrefix,
                listIndent, listDepth, start));
    }

    private static int fenceLength(String line, char expected, int minimum,
                                   boolean closing) {
        int start = 0;
        while (start < line.length() && start < 4 && line.charAt(start) == ' ') start++;
        if (start > 3 || start == line.length()) return 0;
        char marker = line.charAt(start);
        if (expected == 0 ? marker != '`' && marker != '~' : marker != expected) return 0;
        int end = start;
        while (end < line.length() && line.charAt(end) == marker) end++;
        if (end - start < minimum || closing && !line.substring(end).trim().isEmpty()) return 0;
        return end - start;
    }

    private static List<String> tableCells(String line) {
        String trimmed = line.trim();
        if (trimmed.length() < 5 || trimmed.charAt(0) != '|'
                || trimmed.charAt(trimmed.length() - 1) != '|') return null;
        String[] parts = trimmed.substring(1, trimmed.length() - 1).split("\\|", -1);
        if (parts.length < 2) return null;
        List<String> cells = new ArrayList<>(parts.length);
        for (String part : parts) cells.add(part.trim());
        return cells;
    }

    private static boolean isTableSeparator(String line, int columns) {
        List<String> cells = tableCells(line);
        if (cells == null || cells.size() != columns) return false;
        for (String cell : cells) {
            if (!cell.matches(":?-{3,}:?")) return false;
        }
        return true;
    }

    private static void appendInline(String line, int from, int end, StringBuilder text,
                                     List<Mark> marks, int depth) {
        if (depth >= MAX_NESTING) {
            text.append(line, from, end);
            return;
        }
        int i = from;
        while (i < end) {
            char ch = line.charAt(i);
            if (ch == '\\' && i + 1 < end && escapable(line.charAt(i + 1))) {
                text.append(line.charAt(i + 1));
                i += 2;
                continue;
            }
            int kind;
            String marker;
            if (ch == '`') {
                kind = CODE;
                marker = "`";
            } else if (ch == '*' && i + 1 < end && line.charAt(i + 1) == '*') {
                kind = BOLD;
                marker = "**";
            } else if (ch == '*') {
                kind = ITALIC;
                marker = "*";
            } else {
                text.append(ch);
                i++;
                continue;
            }

            if (kind != CODE && (i + marker.length() >= end
                    || Character.isWhitespace(line.charAt(i + marker.length())))) {
                text.append(marker);
                i += marker.length();
                continue;
            }

            int close = findClose(line, marker, i + marker.length(), end);
            if (close < 0) {
                // A streaming answer may not have received its closing marker yet.
                text.append(line, i, end);
                return;
            }
            int start = text.length();
            if (kind == CODE) {
                text.append(line, i + 1, close);
            } else {
                appendInline(line, i + marker.length(), close, text, marks, depth + 1);
            }
            if (text.length() > start) marks.add(new Mark(start, text.length(), kind));
            i = close + marker.length();
        }
    }

    private static int findClose(String line, String marker, int from, int end) {
        boolean inCode = false;
        for (int i = from; i + marker.length() <= end; i++) {
            if (line.charAt(i) == '\\' && i + 1 < end) {
                i++;
                continue;
            }
            if (marker.charAt(0) != '`' && line.charAt(i) == '`') {
                inCode = !inCode;
                continue;
            }
            if (inCode) continue;
            if (!line.startsWith(marker, i)) continue;
            if (marker.length() == 1 && marker.charAt(0) == '*'
                    && ((i > 0 && line.charAt(i - 1) == '*')
                    || (i + 1 < end && line.charAt(i + 1) == '*'))) continue;
            if (marker.charAt(0) == '*' && (i == from
                    || Character.isWhitespace(line.charAt(i - 1)))) continue;
            return i;
        }
        return -1;
    }

    private static boolean escapable(char ch) {
        return ch == '*' || ch == '`' || ch == '\\';
    }

    private static boolean isListSpace(char ch) {
        return ch == ' ' || ch == '\t';
    }

    private static boolean isHorizontalRule(String line) {
        char marker = 0;
        int count = 0;
        for (int i = 0; i < line.length(); i++) {
            char ch = line.charAt(i);
            if (isListSpace(ch)) continue;
            if (ch != '-' && ch != '*' && ch != '_') return false;
            if (marker != 0 && ch != marker) return false;
            marker = ch;
            count++;
        }
        return count >= 3;
    }
}

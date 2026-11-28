package os.opos.launcher;

/** Host-side checks for the parser's visible text and style ranges. */
public final class AnswerMarkdownParserTest {
    public static void main(String[] args) {
        AnswerMarkdownParser.Result mixed = AnswerMarkdownParser.parse(
                "First **Vertex Processing** uses *light* and `**literal**`.");
        equal("First Vertex Processing uses light and **literal**.", mixed.text);
        mark(mixed, "Vertex Processing", AnswerMarkdownParser.BOLD);
        mark(mixed, "light", AnswerMarkdownParser.ITALIC);
        mark(mixed, "**literal**", AnswerMarkdownParser.CODE);
        equal(3, mixed.marks.size());

        AnswerMarkdownParser.Result partial = AnswerMarkdownParser.parse("First **Vert");
        equal("First **Vert", partial.text);
        equal(0, partial.marks.size());
        AnswerMarkdownParser.Result closed = AnswerMarkdownParser.parse("First **Vertex**");
        equal("First Vertex", closed.text);
        mark(closed, "Vertex", AnswerMarkdownParser.BOLD);

        AnswerMarkdownParser.Result blocks = AnswerMarkdownParser.parse(
                "# Stages\n\n- **first** item that wraps\n12. next item\n<b>raw</b> [link](x)");
        equal("Stages\n\n• first item that wraps\n12. next item\n<b>raw</b> [link](x)",
                blocks.text);
        mark(blocks, "Stages", AnswerMarkdownParser.BOLD);
        mark(blocks, "first", AnswerMarkdownParser.BOLD);
        equal(2, blocks.lists.size());
        equal("• ", blocks.lists.get(0).prefix);
        equal("12. ", blocks.lists.get(1).prefix);
        equal(blocks.text.indexOf("• "), blocks.lists.get(0).start);
        equal(blocks.text.indexOf("12. "), blocks.lists.get(0).end);
        equal(blocks.text.indexOf("12. "), blocks.lists.get(1).start);

        AnswerMarkdownParser.Result bullets = AnswerMarkdownParser.parse(
                "- one\n*   two\n+\tthree\n-\t  four");
        equal("• one\n• two\n• three\n• four", bullets.text);
        equal(4, bullets.lists.size());
        listItem(bullets, 0, "• ", 0);
        listItem(bullets, 1, "• ", bullets.text.indexOf("\n") + 1);
        listItem(bullets, 2, "• ", bullets.text.indexOf("\n", bullets.lists.get(1).start) + 1);
        listItem(bullets, 3, "• ", bullets.text.indexOf("\n", bullets.lists.get(2).start) + 1);

        AnswerMarkdownParser.Result numbered = AnswerMarkdownParser.parse(
                "1. first\n1)\tsecond\n12) \tthird");
        equal("1. first\n1) second\n12) third", numbered.text);
        equal(3, numbered.lists.size());
        listItem(numbered, 0, "1. ", 0);
        listItem(numbered, 1, "1) ", numbered.text.indexOf("\n") + 1);
        listItem(numbered, 2, "12) ", numbered.text.lastIndexOf("\n") + 1);

        AnswerMarkdownParser.Result indented = AnswerMarkdownParser.parse(
                "  - two\n   * three\n    + four\n  1. numbered\n    2)\titem");
        equal("  • two\n   • three\n    • four\n  1. numbered\n    2) item", indented.text);
        equal(5, indented.lists.size());
        listItem(indented, 0, "  • ", 0);
        listItem(indented, 1, "   • ", indented.text.indexOf("\n") + 1);
        listItem(indented, 2, "    • ", indented.text.indexOf("\n", indented.lists.get(1).start) + 1);
        listItem(indented, 3, "  1. ", indented.text.indexOf("\n", indented.lists.get(2).start) + 1);
        listItem(indented, 4, "    2) ", indented.text.lastIndexOf("\n") + 1);
        equal(0, indented.lists.get(0).depth);
        equal(0, indented.lists.get(1).depth);
        equal(2, indented.lists.get(2).depth);
        equal(2, indented.lists.get(4).depth);
        equal(2, indented.lists.get(0).indent);
        equal(4, indented.lists.get(2).indent);

        AnswerMarkdownParser.Result cleanStart = AnswerMarkdownParser.parse(
                " \n   answer\n  - nested item\n    2) next item");
        equal("answer\n  • nested item\n    2) next item", cleanStart.text);
        equal(2, cleanStart.lists.size());
        listItem(cleanStart, 0, "  • ", cleanStart.text.indexOf("  • "));
        listItem(cleanStart, 1, "    2) ", cleanStart.text.indexOf("    2) "));
        equal(2, cleanStart.lists.get(0).indent);
        equal(4, cleanStart.lists.get(1).indent);
        equal("", AnswerMarkdownParser.parse(" \t\n").text);
        AnswerMarkdownParser.Result firstList = AnswerMarkdownParser.parse(
                "\n  - first\n    - second");
        equal("  • first\n    • second", firstList.text);
        listItem(firstList, 0, "  • ", 0);
        listItem(firstList, 1, "    • ", firstList.text.indexOf("    • "));
        AnswerMarkdownParser.Result oneSpace = AnswerMarkdownParser.parse("\n 1. first");
        equal("1. first", oneSpace.text);
        equal(1, oneSpace.lists.size());
        listItem(oneSpace, 0, "1. ", 0);
        AnswerMarkdownParser.Result firstCode = AnswerMarkdownParser.parse(
                AnswerDisplay.text("gpu", "\r\n    if ready:\n        run()"));
        equal("    if ready:\n        run()", firstCode.text);
        equal("\tif ready:\n\t\trun()", AnswerMarkdownParser.parse(
                "\n\tif ready:\n\t\trun()").text);

        AnswerMarkdownParser.Result gemma = AnswerMarkdownParser.parse(
                "1. Install drivers\n * Download the latest NVIDIA drivers.\n\n2. Configure ...");
        equal("1. Install drivers\n • Download the latest NVIDIA drivers.\n\n2. Configure ...",
                gemma.text);
        equal(3, gemma.lists.size());
        listItem(gemma, 0, "1. ", 0);
        listItem(gemma, 1, " • ", gemma.text.indexOf('\n') + 1);
        listItem(gemma, 2, "2. ", gemma.text.indexOf("2. Configure"));
        equal(1, gemma.lists.get(1).indent);
        equal(1, gemma.lists.get(1).depth);
        equal(0, gemma.lists.get(2).depth);

        for (String marker : new String[] {"-", "*", "+"}) {
            for (int spaces = 1; spaces <= 4; spaces++) {
                String padding = " ".repeat(spaces);
                AnswerMarkdownParser.Result variant = AnswerMarkdownParser.parse(
                        "1. parent\n" + padding + marker + " child");
                equal("1. parent\n" + padding + "• child", variant.text);
                equal(2, variant.lists.size());
                listItem(variant, 1, padding + "• ", variant.text.indexOf('\n') + 1);
                equal(spaces == 4 ? 2 : 1, variant.lists.get(1).depth);
            }
        }
        AnswerMarkdownParser.Result chained = AnswerMarkdownParser.parse(
                "1. parent\n * first\n + second\n - third");
        equal("1. parent\n • first\n • second\n • third", chained.text);
        equal(4, chained.lists.size());
        for (int i = 1; i < chained.lists.size(); i++) {
            equal(1, chained.lists.get(i).depth);
        }
        AnswerMarkdownParser.Result mixedChildren = AnswerMarkdownParser.parse(
                "1. parent\n - first\n  + second\n   * third");
        equal("1. parent\n • first\n  • second\n   • third", mixedChildren.text);
        equal(4, mixedChildren.lists.size());
        for (int i = 1; i < mixedChildren.lists.size(); i++) {
            equal(1, mixedChildren.lists.get(i).depth);
        }
        AnswerMarkdownParser.Result standalone = AnswerMarkdownParser.parse(
                "plain text\n * top level\n\n1. parent\n\n + also top level");
        equal("plain text\n • top level\n\n1. parent\n\n • also top level",
                standalone.text);
        equal(3, standalone.lists.size());
        equal(0, standalone.lists.get(0).depth);
        equal(0, standalone.lists.get(2).depth);
        for (int spaces = 1; spaces <= 3; spaces++) {
            String padding = " ".repeat(spaces);
            AnswerMarkdownParser.Result orphan = AnswerMarkdownParser.parse(
                    "plain text\n" + padding + "- top level");
            equal("plain text\n" + padding + "• top level", orphan.text);
            equal(1, orphan.lists.size());
            equal(0, orphan.lists.get(0).depth);
        }
        AnswerMarkdownParser.Result tabChild = AnswerMarkdownParser.parse(
                "1. parent\n -\tchild");
        equal("1. parent\n • child", tabChild.text);
        equal(1, tabChild.lists.get(1).depth);
        AnswerMarkdownParser.Result leadingInline = AnswerMarkdownParser.parse(
                "**bold**\n*italic*\n 1. plain text");
        equal("bold\nitalic\n 1. plain text", leadingInline.text);
        equal(0, leadingInline.lists.size());
        mark(leadingInline, "bold", AnswerMarkdownParser.BOLD);
        mark(leadingInline, "italic", AnswerMarkdownParser.ITALIC);

        AnswerMarkdownParser.Result notLists = AnswerMarkdownParser.parse(
                "**bold**\n *no space\n     + five spaces\n-no space\n1)no space");
        equal("bold\n *no space\n     + five spaces\n-no space\n1)no space",
                notLists.text);
        mark(notLists, "bold", AnswerMarkdownParser.BOLD);
        equal(0, notLists.lists.size());
        AnswerMarkdownParser.Result italicStart = AnswerMarkdownParser.parse(
                "*italic* starts a line\r\n  - nested text that wraps\r\n"
                + "    12) next nested text that wraps\r\n");
        equal("italic starts a line\n  • nested text that wraps\n"
                + "    12) next nested text that wraps\n", italicStart.text);
        mark(italicStart, "italic", AnswerMarkdownParser.ITALIC);
        equal(2, italicStart.lists.size());
        equal(0, italicStart.lists.get(0).depth);
        equal(2, italicStart.lists.get(1).depth);
        equal(4, italicStart.lists.get(0).prefix.length());
        equal(8, italicStart.lists.get(1).prefix.length());

        AnswerMarkdownParser.Result nested = AnswerMarkdownParser.parse(
                "**bold *italic* end** and \\*literal\\*");
        equal("bold italic end and *literal*", nested.text);
        mark(nested, "bold italic end", AnswerMarkdownParser.BOLD);
        mark(nested, "italic", AnswerMarkdownParser.ITALIC);
        equal(2, nested.marks.size());

        AnswerMarkdownParser.Result codeInsideBold = AnswerMarkdownParser.parse(
                "**text `code **` still**");
        equal("text code ** still", codeInsideBold.text);
        mark(codeInsideBold, "text code ** still", AnswerMarkdownParser.BOLD);
        mark(codeInsideBold, "code **", AnswerMarkdownParser.CODE);
        equal("a * b * c", AnswerMarkdownParser.parse("a * b * c").text);
        AnswerMarkdownParser.Result multiline = AnswerMarkdownParser.parse(
                "**bold\ncontinued**");
        equal("bold\ncontinued", multiline.text);
        mark(multiline, "bold\ncontinued", AnswerMarkdownParser.BOLD);

        equal("one\n\ntwo\n", AnswerMarkdownParser.parse("one\r\n\r\ntwo\r").text);
        AnswerMarkdownParser.Result rules = AnswerMarkdownParser.parse(
                "before\n---\nafter\n* * *\n_ _ _\n-----\n**bold**");
        equal("before\n\nafter\n\n\n\nbold", rules.text);
        mark(rules, "bold", AnswerMarkdownParser.BOLD);
        for (String marker : new String[] {"---", "***", "___", " - - - "}) {
            equal("above\n\nbelow", AnswerMarkdownParser.parse(
                    "above\n" + marker + "\nbelow").text);
        }

        AnswerMarkdownParser.Result fenced = AnswerMarkdownParser.parse(
                "before\n```java\n**literal** `raw`\nline *two*\n```\nafter");
        equal("before\n**literal** `raw`\nline *two*\nafter", fenced.text);
        mark(fenced, "**literal** `raw`\nline *two*\n", AnswerMarkdownParser.CODE);
        equal(1, fenced.marks.size());
        AnswerMarkdownParser.Result tildeFence = AnswerMarkdownParser.parse(
                "~~~ python\n# **literal**\n~~~");
        equal("# **literal**", tildeFence.text);
        mark(tildeFence, "# **literal**", AnswerMarkdownParser.CODE);
        equal(1, tildeFence.marks.size());
        AnswerMarkdownParser.Result indentedFence = AnswerMarkdownParser.parse(
                "   ```\n**literal**\n   ```");
        equal("**literal**", indentedFence.text);
        mark(indentedFence, "**literal**", AnswerMarkdownParser.CODE);
        AnswerMarkdownParser.Result firstFence = AnswerMarkdownParser.parse(
                "\n   ```\n    if ready:\n   ```");
        equal("    if ready:", firstFence.text);
        mark(firstFence, "    if ready:", AnswerMarkdownParser.CODE);
        AnswerMarkdownParser.Result openFence = AnswerMarkdownParser.parse(
                "```js\n**still literal**\n> no quote");
        equal("**still literal**\n> no quote", openFence.text);
        mark(openFence, openFence.text, AnswerMarkdownParser.CODE);
        equal(1, openFence.marks.size());
        equal(0, openFence.quotes.size());
        AnswerMarkdownParser.Result closedStream = AnswerMarkdownParser.parse(
                "```\n**literal**\n```\n**styled**");
        equal("**literal**\nstyled", closedStream.text);
        mark(closedStream, "**literal**\n", AnswerMarkdownParser.CODE);
        mark(closedStream, "styled", AnswerMarkdownParser.BOLD);

        AnswerMarkdownParser.Result table = AnswerMarkdownParser.parse(
                "| a | b |\n|---|---|\n| c | d |\nparagraph");
        equal("a  ·  b\nc  ·  d\nparagraph", table.text);
        mark(table, "a  ·  b", AnswerMarkdownParser.BOLD);
        equal(1, table.marks.size());
        equal(0, table.lists.size());
        AnswerMarkdownParser.Result alignedTable = AnswerMarkdownParser.parse(
                "| Name | State |\n| :--- | ---: |\n| PC | ready |");
        equal("Name  ·  State\nPC  ·  ready", alignedTable.text);
        mark(alignedTable, "Name  ·  State", AnswerMarkdownParser.BOLD);

        AnswerMarkdownParser.Result quote = AnswerMarkdownParser.parse(
                "> quoted **bold**\n> second line\nplain");
        equal("quoted bold\nsecond line\nplain", quote.text);
        mark(quote, "bold", AnswerMarkdownParser.BOLD);
        equal(2, quote.quotes.size());
        equal(0, quote.quotes.get(0).start);
        equal(quote.text.indexOf('\n') + 1, quote.quotes.get(0).end);
        equal(quote.text.indexOf("second line"), quote.quotes.get(1).start);
        equal(quote.text.indexOf("plain"), quote.quotes.get(1).end);

        AnswerMarkdownParser.Result hierarchy = AnswerMarkdownParser.parse(
                "1. parent\n * child with wrapped text");
        equal(1, hierarchy.lists.get(1).depth);
        AnswerMarkdownLayout.Margins parent = AnswerMarkdownLayout.list(
                0, 3, 4, hierarchy.lists.get(0).depth);
        AnswerMarkdownLayout.Margins child = AnswerMarkdownLayout.list(
                1, 2, 4, hierarchy.lists.get(1).depth);
        equal(0, parent.first);
        equal(3, child.first);
        equal(4, hierarchy.lists.get(1).indent + child.first);
        equal(6, child.rest);
        equal(2, AnswerMarkdownLayout.quote(2));
        System.out.println("AnswerMarkdownParserTest: OK");
    }

    private static void mark(AnswerMarkdownParser.Result result, String content, int kind) {
        int start = result.text.indexOf(content);
        if (start < 0) throw new AssertionError("Missing content: " + content);
        for (AnswerMarkdownParser.Mark mark : result.marks) {
            if (mark.kind == kind && mark.start == start && mark.end == start + content.length()) {
                return;
            }
        }
        throw new AssertionError("Missing style range: " + content + " kind=" + kind);
    }

    private static void listItem(AnswerMarkdownParser.Result result, int index,
                                 String prefix, int start) {
        AnswerMarkdownParser.ListItem item = result.lists.get(index);
        equal(prefix, item.prefix);
        equal(start, item.start);
        int newline = result.text.indexOf('\n', start);
        equal(newline < 0 ? result.text.length() : newline + 1, item.end);
    }

    private static void equal(Object expected, Object actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError("Expected " + expected + " but got " + actual);
        }
    }
}

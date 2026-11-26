# Bundled fonts (OPOS GPU Link typography)

Two families only. Both are under the SIL Open Font License 1.1 (license text next to this file). Downloaded 25 Nov 2026, about 1:05 AM PST, from the official upstream GitHub releases; files copied unmodified except for renaming to Android resource names.

| Resource (app/src/main/res/font/) | Upstream file | SHA-256 |
| --- | --- | --- |
| source_serif_display_black.ttf | SourceSerif4Display-Black.ttf | bb82537dd5a4ddf033bc2625a2e1d6ecf7b201ad597bec540b9dcc8be90f0737 |
| source_serif_subhead_bold.ttf | SourceSerif4Subhead-Bold.ttf | f6565a2362b5878b2a69193f857076ef7bdaa8d7bf51cdcc65231045ff5ba46f |
| source_serif_smtext_regular.ttf | SourceSerif4SmText-Regular.ttf | 54379656e8fa22bfbb7a783f8fe4269c9ae4eb966c1c3fcb17ee3b50cba95813 |
| source_serif_smtext_bold.ttf | SourceSerif4SmText-Bold.ttf | 072c77a0dbffbcb7e99dda31de16e096bd99d1345fd6037d3e153ea315547c25 |
| inter_medium.ttf | extras/ttf/Inter-Medium.ttf | 97ad806f526e41546d46365bb3a393145f75b7b1568913db74549ad8b8dba872 |
| inter_semibold.ttf | extras/ttf/Inter-SemiBold.ttf | 78a843fade9d4612a5567302fb595b56976eb5fcebf4fea5a5912d638bafcde3 |

- Source Serif 4, version 4.005R, Adobe. Release asset `source-serif-4.005_Desktop.zip` (SHA-256 549fdb8f9a682bd06944298621404969f6de77c2e422ff3b8244a1dcd6a0c425) from https://github.com/adobe-fonts/source-serif/releases/tag/4.005R. License: `source-serif-4/LICENSE.md` (OFL 1.1, Reserved Font Name "Source").
- Inter, version 4.1, The Inter Project Authors. Release asset `Inter-4.1.zip` (SHA-256 9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e) from https://github.com/rsms/inter/releases/tag/v4.1. License: `inter/LICENSE.txt` (OFL 1.1).

OFL 1.1 allows bundling in an application. The fonts are not sold on their own and are not renamed as fonts (only the resource file names changed). Reserved Font Names are not used for modified versions because no font was modified.

## Added 25 November 2026, typography options v2

Additional official OFL cuts, copied unmodified except for Android resource file names. Used so card typography can use the correct Source Serif 4 optical size for body (Text, not Small Text), a Semibold subhead, Newsreader's 16pt/72pt optical sizes, Inter Regular, and JetBrains Mono for tabular status and tok/s.

| Resource (app/src/main/res/font/) | Upstream file | SHA-256 |
| --- | --- | --- |
| source_serif_text_regular.ttf | SourceSerif4-Regular.ttf | e5a4ee6a3d87bb9024796be390c6771e2a0eb1883dae25effaf57ca01668e24b |
| source_serif_text_semibold.ttf | SourceSerif4-Semibold.ttf | 36db62940cb5728b12b1802476dc7fcf4c6c519a7bdd476ba23a4e555fc4655f |
| source_serif_text_italic.ttf | SourceSerif4-It.ttf | 9d2950a8f1da66e21502c35d646a1d2148e79f9ea43fd2158cf02f5232e7f430 |
| source_serif_subhead_semibold.ttf | SourceSerif4Subhead-Semibold.ttf | d8f7910a7d891240af43eb79d9e130e71956d500e3bac4d5db122e090bec2fbe |
| inter_regular.ttf | extras/ttf/Inter-Regular.ttf | 40d692fce188e4471e2b3cba937be967878f631ad3ebbbdcd587687c7ebe0c82 |
| jetbrains_mono_medium.ttf | fonts/ttf/JetBrainsMono-Medium.ttf | 31c92d01a8a08528b718a43addf0ad3df0af2ca4b7b3290a452f70f358e14d3d |
| newsreader_16pt_regular.ttf | fonts/static/ttf/Newsreader16pt-Regular.ttf | 0636887c9f72f77ce188f0b31029be58e65adae5a47e6d2887ad5020c2c75036 |
| newsreader_16pt_italic.ttf | fonts/static/ttf/Newsreader16pt-Italic.ttf | 292646cbb948153511e308fa80def59959746d70114bd0936ba0a7f67a33181d |
| newsreader_72pt_semibold.ttf | fonts/static/ttf/Newsreader72pt-SemiBold.ttf | 5b751eeb9894eea0364ada1675ae1b48b544bd98617a349ca0cd134f0f746f1b |

- Source Serif 4 Text / Subhead Semibold cuts: same 4.005R desktop zip as above (SHA-256 549fdb8f9a682bd06944298621404969f6de77c2e422ff3b8244a1dcd6a0c425). The "Text" optical size is the unsuffixed `SourceSerif4-*.ttf` family, intended for 12–18pt; Small Text is too small-optical for 17sp body.
- Inter Regular: same Inter 4.1 zip as above (SHA-256 9883fdd4a49d4fb66bd8177ba6625ef9a64aa45899767dde3d36aa425756b11e).
- JetBrains Mono, version 2.304, The JetBrains Mono Project Authors. Release asset `JetBrainsMono-2.304.zip` (SHA-256 6f6376c6ed2960ea8a963cd7387ec9d76e3f629125bc33d1fdcd7eb7012f7bbf) from https://github.com/JetBrains/JetBrainsMono/releases/tag/v2.304. License: `jetbrains-mono/OFL.txt` (OFL 1.1).
- Newsreader, Production Type / The Newsreader Project Authors. Static optical-size TTFs from https://github.com/productiontype/Newsreader (`fonts/static/ttf/`, master as fetched 25 Nov 2026). License: `newsreader/OFL.txt` (OFL 1.1, Copyright 2020 The Newsreader Project Authors). 16pt cuts for body, 72pt Semibold for card headers.

All of the above remain under OFL 1.1. They are bundled, not sold, and not renamed as fonts.

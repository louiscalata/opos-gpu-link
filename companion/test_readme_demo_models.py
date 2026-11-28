# SPDX-License-Identifier: Apache-2.0
"""Check current card names and the dated file inventory without reading model files."""

import re
import unittest
from pathlib import Path


README = Path(__file__).resolve().parents[1] / "README.md"


class DemoModelReadmeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        readme = README.read_text(encoding="utf-8")
        cls.current = readme.split("## What you will see\n", 1)[1].split("\n## ", 1)[0]
        cls.section = readme.split("## Recorded model files (27 Nov 2026)\n", 1)[1].split("\n## ", 1)[0]
        current_files, earlier_files = cls.section.split("### Earlier lineup\n", 1)

        def table(part):
            lines = [line for line in part.splitlines() if line.startswith("| ")]
            header = lines[0].strip("| ").split(" | ")
            rows = {
                cells[0]: cells
                for cells in (line.strip("| ").split(" | ") for line in lines[2:])
            }
            return header, rows

        cls.header, cls.rows = table(current_files)
        cls.earlier_header, cls.earlier_rows = table(earlier_files)

    def test_current_cards_have_owner_names_without_invented_file_details(self):
        lines = [line for line in self.current.splitlines() if line.startswith("| ")]
        self.assertEqual(lines[0], "| Card | Model | Maker | Role |")
        cards = [
            (cells[0], cells[1:])
            for cells in (line.strip("| ").split(" | ") for line in lines[2:])
        ]
        self.assertEqual(cards, [
            ("Computer", ["Nemotron 3.5 Bolt", "NVIDIA", "Primary; runs on the computer GPU"]),
            ("Phone `m1`", ["Nemotron Mini 4B", "NVIDIA", "Phone model"]),
            ("Phone `m2`", ["Qwen3.5-2B", "Qwen (Alibaba)", "Phone model"]),
            ("Phone `m3`", ["LFM2 1.2B (baseline)", "Liquid AI", "Baseline (comparison)"]),
            ("Phone `m4`", ["Granite 4.1 3B", "IBM", "Phone model"]),
        ])
        self.assertNotIn("AceInstruct", self.current)
        for line in lines[2:]:
            with self.subTest(card=line):
                self.assertNotRegex(line, r"(?i)\.gguf|\b\d+(?:\.\d+)?\s*(?:GB|bytes)\b|\b[0-9a-f]{64}\b")

    def test_recorded_files_match_supplied_on_disk_values(self):
        self.assertEqual(self.header, ["Where", "Model", "File", "Size", "SHA-256", "License"])
        self.assertEqual(self.earlier_header, self.header)
        expected = (
            ("MacBook (Metal)", "Nemotron-3.5-Bolt-E4B-Q4_K_M.gguf", 6180446208,
             "c8af2b8aea10a690a1d9491db744a9446660173cb38fc489612b556615a69612", "OpenMDW-1.1"),
            ("Phone `m1`", "Nemotron-Mini-4B-Instruct-Q4_K_M.gguf", 2697387072,
             "2bf02846dbd45e9580b9338b90505fb54e00d185713d4b7f06699e2d5d298e48", "NVIDIA Open Model License"),
            ("Phone `m3` (baseline)", "LFM2-1.2B-Q4_K_M.gguf", 730893248,
             "55175400e3f509a9616227afeffd58d87e80b9f628a5d3d54ada884d85221fed", "LFM Open License v1.0"),
        )
        self.assertEqual(len(self.rows), len(expected))
        for role, filename, size, digest, license_name in expected:
            with self.subTest(role=role):
                row = self.rows[role]
                self.assertEqual(row[2], f"`{filename}`")
                self.assertEqual(row[3], f"{size / 1_000_000_000:.2f} GB ({size:,} bytes)")
                self.assertEqual(row[4], f"`{digest}`")
                self.assertIn(license_name, row[5])
        earlier = self.earlier_rows["Phone, former lead"]
        self.assertEqual(earlier[2], "`nvidia_AceInstruct-1.5B-Q4_K_M.gguf`")
        self.assertEqual(earlier[3], "1.12 GB (1,117,318,944 bytes)")
        self.assertEqual(earlier[4], "`103b7fa617d2b3c2d6e168a878b9b5e3710d19d178bf4b890acf0fac2abafadb`")
        self.assertIn("CC-BY-NC-4.0", earlier[5])
        self.assertIn("on the demo MacBook on 27 Nov 2026 (America/Los_Angeles)", self.section)

    def test_gemma_comparison_has_size_but_no_invented_digest(self):
        self.assertEqual(len(self.earlier_rows), 2)
        row = self.earlier_rows["MacBook, comparison only"]
        self.assertEqual(row[2], "`gemma-4-26B_q4_0-it.gguf`")
        self.assertEqual(row[3], "14.44 GB (14,439,363,584 bytes)")
        self.assertEqual(row[4], "Not recorded")
        self.assertIn("Apache-2.0", row[5])
        self.assertIsNone(re.search(r"\b[0-9a-f]{64}\b", " | ".join(row), flags=re.IGNORECASE))
        self.assertIn("Gemma's SHA-256 was not recorded while LM Studio was serving it.", self.section)


if __name__ == "__main__":
    unittest.main()

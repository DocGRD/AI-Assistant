"""M5.5 — watcher units: frontmatter parsing + content chunking. Stdlib unittest."""

import unittest

from assistant_core.watcher.frontmatter_parser import FrontmatterParser
from assistant_core.watcher.content_chunker import ContentChunker


class FrontmatterTests(unittest.TestCase):
    def test_extract_frontmatter_and_body(self):
        fm, body = FrontmatterParser.extract(
            "---\nassistant-status: pending\nassistant-request: hello\n---\n\nBody text here\n")
        self.assertEqual(fm.get("assistant-status"), "pending")
        self.assertEqual(fm.get("assistant-request"), "hello")
        self.assertIn("Body text here", body)
        self.assertNotIn("assistant-status", body)

    def test_no_frontmatter_returns_content_unchanged(self):
        fm, body = FrontmatterParser.extract("Just text, no frontmatter")
        self.assertEqual(fm, {})
        self.assertEqual(body, "Just text, no frontmatter")


class ChunkerTests(unittest.TestCase):
    def test_small_content_is_one_chunk(self):
        self.assertEqual(ContentChunker(max_tokens=4000).chunk_content("a short note"), ["a short note"])

    def test_large_content_is_split(self):
        big = "\n\n".join(f"## Section {i}\n\n" + ("word " * 400) for i in range(8))
        chunks = ContentChunker(max_tokens=200).chunk_content(big)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.strip() for c in chunks))


if __name__ == "__main__":
    unittest.main()

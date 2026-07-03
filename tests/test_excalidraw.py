"""M19 Slice 1 — Excalidraw text extraction + indexer integration. Stdlib unittest."""

import unittest

from assistant_core.media.excalidraw import (
    is_excalidraw, extract_excalidraw_text,
)

_NOTE = """---
excalidraw-plugin: parsed
tags: [excalidraw]
---
==⚠ Switch to EXCALIDRAW VIEW ...==

# Excalidraw Data

## Text Elements
Big Idea: God's anointing equips His children ^9dqBQi06

Gospel solution: Christ exposes falsehood

## Drawing
```compressed-json
N4KAkARALgngDgUwgLg...garbage...
```
"""


class IsExcalidrawTests(unittest.TestCase):
    def test_by_path(self):
        self.assertTrue(is_excalidraw("04 - Study/Sermon.excalidraw.md", {}))

    def test_by_frontmatter(self):
        self.assertTrue(is_excalidraw("foo.md", {"excalidraw-plugin": "parsed"}))

    def test_plain_note_is_not(self):
        self.assertFalse(is_excalidraw("notes/plain.md", {"tags": ["x"]}))


class ExtractTests(unittest.TestCase):
    def test_pulls_text_elements_strips_blockids(self):
        text = extract_excalidraw_text(_NOTE)
        self.assertIn("Big Idea: God's anointing equips His children", text)
        self.assertIn("Gospel solution: Christ exposes falsehood", text)
        self.assertNotIn("9dqBQi06", text)            # block id stripped
        self.assertNotIn("compressed-json", text)      # scene JSON excluded
        self.assertNotIn("garbage", text)

    def test_json_fallback(self):
        note = ('## Drawing\n```json\n'
                '{"type":"excalidraw","elements":['
                '{"type":"text","text":"Hello sketch"},'
                '{"type":"rectangle"},'
                '{"type":"text","text":"Second label"}]}\n```\n')
        text = extract_excalidraw_text(note)
        self.assertIn("Hello sketch", text)
        self.assertIn("Second label", text)

    def test_empty_when_no_text(self):
        self.assertEqual(extract_excalidraw_text("# Excalidraw Data\n## Drawing\nnothing\n"), "")

    def test_dedupes(self):
        note = "## Text Elements\nrepeat ^a\nrepeat ^b\nunique ^c\n"
        self.assertEqual(extract_excalidraw_text(note).splitlines().count("repeat"), 1)


if __name__ == "__main__":
    unittest.main()

"""M40 — web clipper: readable text → sourced, indexed note (propose = a new note)."""

import tempfile
import unittest
from pathlib import Path

from assistant_core import clip


_HTML = """<html><head><title>Rocket Stoves 101</title></head>
<body><article><h1>Rocket Stoves</h1>
<p>A rocket stove burns small-diameter wood very efficiently in an insulated J-shaped
combustion chamber. The design draws air upward and mixes it with wood gas.</p>
<p>They are widely used for cooking in off-grid settings.</p></article></body></html>"""


class _Rag:
    def __init__(self):
        self.indexed = []
    def index_note(self, rel, content=None):
        self.indexed.append(rel)
        return 1


class ClipTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_clip_writes_sourced_note(self):
        rag = _Rag()
        r = clip.clip_url(self.tmp, "https://example.com/rocket", rag=rag,
                          fetch_fn=lambda u: _HTML)
        self.assertTrue(r["ok"])
        self.assertTrue(r["path"].startswith("AI/Clippings/"))
        self.assertTrue(r["indexed"])
        body = (Path(self.tmp) / r["path"]).read_text(encoding="utf-8")
        self.assertIn("source: https://example.com/rocket", body)
        self.assertIn("Rocket Stove", body)
        self.assertIn("Clipped from", body)
        self.assertEqual(rag.indexed, [r["path"]])

    def test_bad_url_returns_not_ok(self):
        r = clip.clip_url(self.tmp, "not-a-url")
        self.assertFalse(r["ok"])
        self.assertIsNone(r["path"])

    def test_empty_page_not_clipped(self):
        r = clip.clip_url(self.tmp, "https://example.com/empty", fetch_fn=lambda u: "<html></html>")
        self.assertFalse(r["ok"])

    def test_unique_filenames(self):
        f = lambda u: _HTML
        a = clip.clip_url(self.tmp, "https://a.com", fetch_fn=f)
        b = clip.clip_url(self.tmp, "https://b.com", fetch_fn=f)
        self.assertNotEqual(a["path"], b["path"])   # same title → deduped filename


if __name__ == "__main__":
    unittest.main()

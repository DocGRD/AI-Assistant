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
    def maybe_index_note(self, rel, content):     # single-note incremental path (never full reindex)
        self.indexed.append(rel)
        return True


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

    def test_youtube_transcript_capture(self):      # M40 best-effort YouTube
        watch = ('<html><head><title>Great Talk - YouTube</title></head><body>'
                 '<script>var x = {"captionTracks":[{"baseUrl":'
                 '"https://www.youtube.com/api/timedtext?v=abc","languageCode":"en"}]};</script>'
                 '</body></html>')
        xml = ('<?xml version="1.0"?><transcript>'
               '<text start="0" dur="2">Hello and welcome</text>'
               '<text start="2" dur="3">to this rocket stove talk</text></transcript>')

        def fetch(u):
            return xml if "timedtext" in u else watch

        r = clip.clip_url(self.tmp, "https://www.youtube.com/watch?v=abcdef12345",
                          fetch_fn=fetch)
        self.assertTrue(r["ok"])
        self.assertEqual(r["kind"], "youtube")
        body = (Path(self.tmp) / r["path"]).read_text(encoding="utf-8")
        self.assertIn("tags: [clipping, youtube]", body)
        self.assertIn("Hello and welcome", body)
        self.assertIn("rocket stove talk", body)
        self.assertIn("Transcript captured from", body)

    def test_youtube_no_captions_graceful(self):
        r = clip.clip_url(self.tmp, "https://youtu.be/abcdef12345",
                          fetch_fn=lambda u: "<html><title>x</title>no tracks here</html>")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "no transcript available")


if __name__ == "__main__":
    unittest.main()

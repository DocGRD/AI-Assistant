"""Tests for v1.9 HTML-collection ingest (zip/folder of interlinked HTM → vault notes with
inter-file links rewritten to wikilinks)."""

import tempfile
import unittest
import zipfile
from pathlib import Path

from assistant_core.ingest.htmlset import html_to_markdown, ingest_html_collection
from assistant_core.ingest.ingest import ingest_file


class TestHtmlToMarkdown(unittest.TestCase):
    def test_intra_set_link_becomes_wikilink(self):
        md = html_to_markdown(
            '<p>See <a href="MHC1002.HTM#v2">Gen 2</a>.</p>',
            resolve_link=lambda h: "AI/Library/mh/mhc1002" if "MHC1002" in h else None,
        )
        self.assertIn("[[AI/Library/mh/mhc1002|Gen 2]]", md)
        self.assertNotIn(".HTM", md)

    def test_external_link_kept_unresolved_local_dropped(self):
        md = html_to_markdown(
            '<a href="http://ex.com">web</a> and <a href="missing.htm">gone</a>',
            resolve_link=lambda h: None,
        )
        self.assertIn("[web](http://ex.com)", md)
        self.assertIn("gone", md)
        self.assertNotIn("missing.htm", md)

    def test_headings_and_scripts(self):
        md = html_to_markdown("<h2>Title</h2><script>bad()</script><p>Body</p>")
        self.assertIn("## Title", md)
        self.assertNotIn("bad()", md)


class TestZipIngest(unittest.TestCase):
    def setUp(self):
        self.vault = Path(tempfile.mkdtemp())
        self.zip = self.vault.parent / "matthew_henry.zip"
        with zipfile.ZipFile(self.zip, "w") as zf:
            zf.writestr("MHC1001.HTM", '<html><title>Genesis 1</title><body><h1>Genesis 1</h1>'
                        '<p>Start. See <a href="MHC1002.HTM#v2">Genesis 2</a>.</p></body></html>')
            zf.writestr("MHC1002.HTM", '<html><title>Genesis 2</title><body>'
                        '<p>Back to <a href="MHC1001.HTM">Genesis 1</a>.</p></body></html>')

    def test_zip_creates_notes_with_rewritten_links(self):
        rep = ingest_file(str(self.vault), str(self.zip), {})
        self.assertIsNone(rep.get("error"))
        self.assertEqual(rep["format"], "html-set")
        self.assertEqual(rep["collection"], "matthew-henry")
        self.assertEqual(rep["files"], 2)
        n1 = (self.vault / "AI/Library/matthew-henry/mhc1001.md").read_text(encoding="utf-8")
        n2 = (self.vault / "AI/Library/matthew-henry/mhc1002.md").read_text(encoding="utf-8")
        self.assertIn("[[AI/Library/matthew-henry/mhc1002|Genesis 2]]", n1)
        self.assertIn("[[AI/Library/matthew-henry/mhc1001|Genesis 1]]", n2)
        self.assertNotIn(".HTM", n1)

    def test_folder_of_html_also_works(self):
        d = self.vault.parent / "htmlfolder"
        d.mkdir(exist_ok=True)
        (d / "a.html").write_text('<title>A</title><a href="b.html">to B</a>', encoding="utf-8")
        (d / "b.html").write_text("<title>B</title><p>hello</p>", encoding="utf-8")
        rep = ingest_html_collection(str(self.vault), str(d), {})
        self.assertIsNone(rep.get("error"))
        self.assertEqual(rep["files"], 2)
        na = (self.vault / "AI/Library/htmlfolder/a.md").read_text(encoding="utf-8")
        self.assertIn("[[AI/Library/htmlfolder/b|to B]]", na)

    def test_missing_zip_reports_error(self):
        rep = ingest_file(str(self.vault), "no-such-file.zip", {})
        self.assertTrue(rep.get("error"))


if __name__ == "__main__":
    unittest.main()

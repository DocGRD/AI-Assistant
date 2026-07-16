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
        # A #fragment is preserved as an Obsidian block-ref so the link lands on the exact anchor.
        self.assertIn("[[AI/Library/mh/mhc1002#^v2|Gen 2]]", md)
        self.assertNotIn(".HTM", md)

    def test_element_id_becomes_block_anchor(self):
        # A verse's id -> an Obsidian block anchor at the block end, so cross-references land on it.
        md = html_to_markdown('<p><sup id="v14">14</sup> Behold, the virgin.</p>')
        self.assertRegex(md, r"Behold, the virgin\.\s*\^v14")

    def test_fragment_link_and_anchor_roundtrip(self):
        # source links to #v14; target has id=v14 -> link resolves to the target's block anchor.
        src = html_to_markdown('<p>as in <a href="tgt.html#v14">Isa 7:14</a></p>',
                               resolve_link=lambda h: "AI/Library/b/tgt" if "tgt" in h else None)
        self.assertIn("[[AI/Library/b/tgt#^v14|Isa 7:14]]", src)

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

    def test_body_tag_not_read_as_bold(self):
        # regression: `<body>` starts with "b", so a bold regex without a word boundary read it as
        # `<b>` and paired it with a later </b>, swallowing the heading + verse number into one span.
        md = html_to_markdown('<html><head><title>T</title></head><body>'
                              '<h1>Matthew 1</h1><p><b>1</b> Book.</p></body></html>')
        self.assertIn("# Matthew 1", md)
        self.assertIn("**1** Book.", md)
        self.assertNotIn("**# Matthew 1", md)   # heading must not be captured inside the bold span


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
        self.assertIn("[[AI/Library/matthew-henry/mhc1002#^v2|Genesis 2]]", n1)  # #fragment preserved
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

    def test_cssclasses_and_omit_blockquote_config(self):
        # Bible ingests tag notes with `cssclasses: [bible]` (so layout CSS can target them) and
        # drop the "> Ingested from…" provenance blockquote (it still lives in the frontmatter).
        d = self.vault.parent / "biblefolder"
        d.mkdir(exist_ok=True)
        (d / "gen-1.html").write_text('<title>Genesis 1</title><h1>Genesis 1</h1>'
                                      '<p><b>1</b> In the beginning.</p>', encoding="utf-8")
        rep = ingest_html_collection(str(self.vault), str(d),
              {"htmlset_cssclasses": ["bible"], "htmlset_omit_note_blockquote": True})
        self.assertIsNone(rep.get("error"))
        note = (self.vault / "AI/Library/biblefolder/gen-1.md").read_text(encoding="utf-8")
        self.assertIn("cssclasses:\n  - bible", note)      # tag present for layout targeting
        self.assertNotIn("> Ingested from", note)          # provenance blockquote omitted
        self.assertIn("source:", note)                     # provenance still in frontmatter
        self.assertIn("**1** In the beginning.", note)

    def test_missing_zip_reports_error(self):
        rep = ingest_file(str(self.vault), "no-such-file.zip", {})
        self.assertTrue(rep.get("error"))

    def test_duplicate_basenames_resolve_to_distinct_notes(self):
        # regression: same filename in different folders (a/Note.htm vs b/Note.htm — common in
        # commentary sets) used to collapse to ONE note via a basename-keyed link map. Links must
        # resolve by archive-relative PATH so each points at its own distinct note.
        z = self.vault.parent / "dup.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("a/Note.htm", '<html><body>A to <a href="../b/Note.htm">Bee</a></body></html>')
            zf.writestr("b/Note.htm", '<html><body>B to <a href="../a/Note.htm">Ay</a></body></html>')
            zf.writestr("index.htm", '<html><body><a href="a/Note.htm">a</a> <a href="b/Note.htm">b</a></body></html>')
        rep = ingest_file(str(self.vault), str(z), {})
        self.assertIsNone(rep.get("error"))
        self.assertEqual(rep["files"], 3)                     # note, note-2, index (deduped)
        base = self.vault / "AI/Library/dup"
        idx = (base / "index.md").read_text(encoding="utf-8")
        na = (base / "note.md").read_text(encoding="utf-8")   # from a/Note.htm
        # index links to BOTH distinct notes, not the same one twice
        self.assertIn("[[AI/Library/dup/note|a]]", idx)
        self.assertIn("[[AI/Library/dup/note-2|b]]", idx)
        # a/Note links to b/Note == note-2 (the OTHER file), not itself
        self.assertIn("[[AI/Library/dup/note-2|Bee]]", na)


if __name__ == "__main__":
    unittest.main()

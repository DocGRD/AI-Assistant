"""M22 — document ingestion (extract + write to AI/Library). Stdlib unittest, no deps."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.ingest.extract import extract_document, SUPPORTED
from assistant_core.ingest.ingest import ingest_file, LIBRARY_DIR


class ExtractTests(unittest.TestCase):
    def test_txt_and_md_need_no_dependency(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "notes.txt"
            p.write_text("Hello world. Rocket mass heaters.", encoding="utf-8")
            doc = extract_document(p)
            self.assertTrue(doc["ok"])
            self.assertEqual(doc["format"], "txt")
            self.assertIn("Rocket mass heaters", doc["pages"][0]["text"])

    def test_missing_file_and_unsupported_are_graceful(self):
        self.assertFalse(extract_document("/nope/missing.pdf")["ok"])
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.xyz"; p.write_text("x", encoding="utf-8")
            r = extract_document(p)
            self.assertFalse(r["ok"])
            self.assertIn("unsupported", r["error"])

    def test_supported_list(self):
        self.assertIn(".pdf", SUPPORTED)
        self.assertIn(".epub", SUPPORTED)
        self.assertIn(".docx", SUPPORTED)


class IngestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_ingest_writes_library_note_with_page_anchors(self):
        # inject a fake multi-page extraction (no real PDF needed)
        def fake_extract(path):
            return {"title": "Rocket Handbook", "format": "pdf", "ok": True, "error": None,
                    "pages": [{"page": 1, "heading": None, "text": "Intro to rocket mass heaters."},
                              {"page": 2, "heading": None, "text": "Thermal mass stores heat."}]}
        rep = ingest_file(self.vault, "C:/docs/rocket.pdf", {}, extract_fn=fake_extract)
        self.assertIsNone(rep["error"])
        self.assertEqual(rep["pages"], 2)
        self.assertTrue(rep["note_path"].startswith(LIBRARY_DIR))
        body = (Path(self.vault) / rep["note_path"]).read_text(encoding="utf-8")
        self.assertIn("# Rocket Handbook", body)
        self.assertIn("## Page 1", body)                    # per-page provenance anchor
        self.assertIn("## Page 2", body)
        self.assertIn("Thermal mass stores heat.", body)
        self.assertIn("source: C:/docs/rocket.pdf", body)

    def test_ingest_reports_extraction_error(self):
        def fake_fail(path):
            return {"title": "x", "format": "pdf", "pages": [], "ok": False,
                    "error": "pypdf not installed"}
        rep = ingest_file(self.vault, "x.pdf", {}, extract_fn=fake_fail)
        self.assertIn("pypdf not installed", rep["error"])
        self.assertIsNone(rep["note_path"])

    def test_ingest_real_txt_end_to_end(self):
        src = Path(self.vault) / "src.md"
        src.write_text("# Title\n\nBluebirds belong to the genus Sialia.", encoding="utf-8")
        rep = ingest_file(self.vault, str(src), {})
        self.assertIsNone(rep["error"])
        body = (Path(self.vault) / rep["note_path"]).read_text(encoding="utf-8")
        self.assertIn("Sialia", body)
        self.assertIn("ai-derived: ingested-document", body)

    def test_ingest_resolves_vault_relative_source(self):
        # A vault-relative path (what the plugin/terminal user types) must resolve
        # against the vault, not the process CWD.
        sub = Path(self.vault) / "07 - Reference"
        sub.mkdir(parents=True, exist_ok=True)
        (sub / "spec.txt").write_text("Casters rated to 300 lbs.", encoding="utf-8")
        rep = ingest_file(self.vault, "07 - Reference/spec.txt", {})
        self.assertIsNone(rep["error"], rep)
        body = (Path(self.vault) / rep["note_path"]).read_text(encoding="utf-8")
        self.assertIn("Casters rated", body)


if __name__ == "__main__":
    unittest.main()

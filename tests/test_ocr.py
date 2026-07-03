"""M19 Slices 2-5 — image/handwriting OCR engine. Stdlib unittest (injected fakes)."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.media import ocr as O
from assistant_core.media.ocr import OcrEngine, find_image_embeds, resolve_image_path


class EmbedTests(unittest.TestCase):
    def test_finds_wiki_and_md_embeds(self):
        content = ("Here ![[diagram.png]] and ![alt](images/photo.jpg) and "
                   "![[scan.PNG|200]] and a non-image ![[note.md]].")
        embeds = find_image_embeds(content)
        self.assertIn("diagram.png", embeds)
        self.assertIn("images/photo.jpg", embeds)
        self.assertIn("scan.PNG", embeds)            # size suffix stripped
        self.assertNotIn("note.md", embeds)          # not an image

    def test_dedupes(self):
        self.assertEqual(find_image_embeds("![[a.png]] ![[a.png]]"), ["a.png"])


class ResolveTests(unittest.TestCase):
    def test_direct_and_basename_search(self):
        with tempfile.TemporaryDirectory() as d:
            vault = Path(d)
            (vault / "Attachments").mkdir()
            img = vault / "Attachments" / "pic.png"
            img.write_bytes(b"\x89PNG")
            self.assertEqual(resolve_image_path(vault, "Attachments/pic.png"), img)
            self.assertEqual(resolve_image_path(vault, "pic.png"), img)   # basename search
            self.assertIsNone(resolve_image_path(vault, "missing.png"))


class OcrEngineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        (self.vault / "img.png").write_bytes(b"\x89PNG\x00")
        self.note = self.vault / "Notes" / "scan.md"
        self.note.parent.mkdir(parents=True, exist_ok=True)
        self.note.write_text("# Scan\n\n![[img.png]]\n", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def test_vision_path_writes_sidecar(self):
        seen = {}
        def fake_vision(path, private):
            seen["private"] = private
            return "Handwritten: the last hour\nDescription: a sketch"
        eng = OcrEngine(self.vault, vision_fn=fake_vision, tesseract_fn=lambda p: "")
        rep = eng.ocr_note("Notes/scan.md", private=True)
        self.assertEqual(rep["images"], 1)
        self.assertEqual(rep["ocred"], 1)
        self.assertEqual(rep["engine"], ["vision"])
        self.assertTrue(seen["private"])                       # privacy threaded to vision
        sidecar = self.vault / rep["sidecar"]
        self.assertTrue(sidecar.exists())
        body = sidecar.read_text(encoding="utf-8")
        self.assertIn("Handwritten: the last hour", body)
        self.assertIn("ai-derived: ocr", body)
        self.assertIn("[[scan]]", body)                        # backlink to source
        # original untouched
        self.assertEqual(self.note.read_text(encoding="utf-8"), "# Scan\n\n![[img.png]]\n")

    def test_falls_back_to_tesseract(self):
        eng = OcrEngine(self.vault, vision_fn=lambda p, pr: None,
                        tesseract_fn=lambda p: "PRINTED TEXT")
        rep = eng.ocr_note("Notes/scan.md")
        self.assertEqual(rep["engine"], ["tesseract"])
        self.assertIn("PRINTED TEXT", (self.vault / rep["sidecar"]).read_text(encoding="utf-8"))

    def test_missing_image_is_reported_not_fatal(self):
        self.note.write_text("![[gone.png]]\n", encoding="utf-8")
        eng = OcrEngine(self.vault, vision_fn=lambda p, pr: "x", tesseract_fn=lambda p: "")
        rep = eng.ocr_note("Notes/scan.md")
        self.assertEqual(rep["ocred"], 0)
        self.assertIn("not found", (self.vault / rep["sidecar"]).read_text(encoding="utf-8"))

    def test_no_images_returns_early(self):
        self.note.write_text("# just text\n", encoding="utf-8")
        rep = OcrEngine(self.vault, vision_fn=lambda p, pr: "x").ocr_note("Notes/scan.md")
        self.assertEqual(rep["images"], 0)
        self.assertIsNone(rep["sidecar"])


class AnalyzeImageTests(unittest.TestCase):
    def test_analyze_uses_vision_then_tesseract(self):
        from assistant_core.media import ocr as O
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "pic.png").write_bytes(b"\x89PNG\x00")
            # no real router → make_vision_fn returns None → falls to tesseract_fn (patched)
            O_tess = O.tesseract_ocr
            try:
                O.tesseract_ocr = lambda p: "TRANSCRIBED TEXT"
                text, err = O.analyze_image(d, "pic.png", router=None, config={})
                self.assertIsNone(err)
                self.assertEqual(text, "TRANSCRIBED TEXT")
            finally:
                O.tesseract_ocr = O_tess

    def test_analyze_missing_image(self):
        from assistant_core.media.ocr import analyze_image
        with tempfile.TemporaryDirectory() as d:
            text, err = analyze_image(d, "nope.png", router=None, config={})
            self.assertIn("not found", err)


class MakeVisionFnTests(unittest.TestCase):
    def test_skips_training_provider_when_private(self):
        from types import SimpleNamespace
        # google = multimodal but trains; groq scout = multimodal + no-train
        specs = {
            "google": SimpleNamespace(strengths=["multimodal"], trains_on_data="yes"),
            "groq:scout": SimpleNamespace(strengths=["multimodal", "fast"], trains_on_data="no"),
        }
        called = {}
        class _P:
            def __init__(self, name): self.name = name
            def describe_image(self, b64, mime, prompt, max_tokens=1024):
                called["name"] = self.name
                return f"text from {self.name}"
        router = SimpleNamespace(registry=SimpleNamespace(specs=specs),
                                 _providers={"google": _P("google"), "groq:scout": _P("groq:scout")})
        with tempfile.TemporaryDirectory() as d:
            img = Path(d) / "x.png"; img.write_bytes(b"\x89PNG")
            vis = O.make_vision_fn(router, {})
            out = vis(img, private=True)
            self.assertEqual(called["name"], "groq:scout")     # skipped google (trains)
            self.assertIn("groq:scout", out)


if __name__ == "__main__":
    unittest.main()

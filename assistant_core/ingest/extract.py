"""
Document text extraction — Milestone 22, Slice 1.

Pull readable text (with page/section structure for provenance) out of PDFs, EPUBs, Word
docs, and plain text/markdown. Heavy format libraries are optional and imported lazily —
if one isn't installed, that format returns a clear error instead of raising, so the rest
of the app is unaffected. `.txt`/`.md` need no dependency.

Returns: {title, format, pages: [{page, heading, text}], ok, error}. `pages` is the unit
of provenance — a PDF page, an EPUB chapter, or the whole doc for flat formats.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("assistant")

SUPPORTED = (".pdf", ".epub", ".docx", ".txt", ".md", ".markdown", ".htm", ".html", ".xhtml")


def _result(title, fmt, pages, error=None):
    return {"title": title, "format": fmt, "pages": pages, "ok": bool(pages) and not error,
            "error": error}


def _extract_txt(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    return _result(path.stem, path.suffix.lstrip("."), [{"page": 1, "heading": None, "text": text}])


def _extract_pdf(path: Path) -> dict:
    try:
        from pypdf import PdfReader
    except Exception:
        return _result(path.stem, "pdf", [], "pypdf not installed (pip install pypdf) — cannot read PDFs")
    try:
        reader = PdfReader(str(path))
        pages = []
        for i, pg in enumerate(reader.pages, 1):
            txt = (pg.extract_text() or "").strip()
            if txt:
                pages.append({"page": i, "heading": None, "text": txt})
        if not pages:
            return _result(path.stem, "pdf", [],
                           "no extractable text (scanned PDF? OCR fallback not enabled)")
        return _result(path.stem, "pdf", pages)
    except Exception as exc:
        return _result(path.stem, "pdf", [], f"PDF read failed: {exc}")


def _extract_epub(path: Path) -> dict:
    try:
        from ebooklib import epub, ITEM_DOCUMENT
        from assistant_core.web.fetch import html_to_text
    except Exception:
        return _result(path.stem, "epub", [], "ebooklib not installed (pip install ebooklib)")
    try:
        book = epub.read_epub(str(path))
        title = (book.get_metadata("DC", "title") or [(path.stem,)])[0][0]
        pages = []
        for i, item in enumerate((it for it in book.get_items() if it.get_type() == ITEM_DOCUMENT), 1):
            txt = html_to_text(item.get_content().decode("utf-8", errors="replace")).strip()
            if txt:
                pages.append({"page": i, "heading": item.get_name(), "text": txt})
        return _result(title, "epub", pages, None if pages else "no text found in EPUB")
    except Exception as exc:
        return _result(path.stem, "epub", [], f"EPUB read failed: {exc}")


def _extract_docx(path: Path) -> dict:
    try:
        import docx
    except Exception:
        return _result(path.stem, "docx", [], "python-docx not installed (pip install python-docx)")
    try:
        doc = docx.Document(str(path))
        # Split into sections at Heading paragraphs so citations can point at a heading.
        sections: list[dict] = [{"page": 1, "heading": None, "lines": []}]
        for p in doc.paragraphs:
            style = (p.style.name if p.style else "") or ""
            if style.startswith("Heading") and p.text.strip():
                sections.append({"page": len(sections) + 1, "heading": p.text.strip(), "lines": []})
            elif p.text.strip():
                sections[-1]["lines"].append(p.text)
        pages = [{"page": s["page"], "heading": s["heading"], "text": "\n\n".join(s["lines"])}
                 for s in sections if s["lines"]]
        return _result(path.stem, "docx", pages, None if pages else "empty document")
    except Exception as exc:
        return _result(path.stem, "docx", [], f"DOCX read failed: {exc}")


def _extract_html(path: Path) -> dict:
    """One HTML file → readable Markdown (dependency-free). External links are kept as Markdown
    links; a whole interlinked set (a .zip/folder) is handled by ingest.htmlset instead."""
    from assistant_core.ingest.htmlset import html_to_markdown, extract_title
    raw = path.read_text(encoding="utf-8", errors="replace")
    md = html_to_markdown(raw)
    title = extract_title(raw, path.stem)
    return _result(title, "html", [{"page": 1, "heading": None, "text": md}] if md else [],
                   None if md else "no readable text in HTML")


def extract_document(path) -> dict:
    """Dispatch by extension. Unsupported/missing → an ok=False result (never raises)."""
    path = Path(path)
    if not path.is_file():
        return _result(path.stem, path.suffix.lstrip("."), [], f"file not found: {path}")
    ext = path.suffix.lower()
    if ext in (".txt", ".md", ".markdown"):
        return _extract_txt(path)
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".epub":
        return _extract_epub(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext in (".htm", ".html", ".xhtml"):
        return _extract_html(path)
    return _result(path.stem, ext.lstrip("."), [], f"unsupported format: {ext or '(none)'}")

"""
Document ingestion — Milestone 22, Slices 2/5.

Extract a document and write it into the vault as a searchable, clearly-AI-derived note
under `AI/Library/` — one `## Page N` / `## Section` block per source page so Vault QA
answers and (later) citations can point at an exact location. The note is a normal
Markdown file, so the M11 indexer / watcher pick it up automatically. Optionally feeds
the M18 knowledge graph. The original file is never modified.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from assistant_core.ingest.extract import extract_document

logger = logging.getLogger("assistant")

LIBRARY_DIR = "AI/Library"


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", (text or "").lower())
    return re.sub(r"\s+", "-", slug).strip("-")[:60] or "document"


def _build_note(doc: dict, source: str, date: str) -> str:
    lines = [
        "---", "ai-derived: ingested-document", f"source: {source}",
        f"format: {doc['format']}", f"pages: {len(doc['pages'])}", f"ingested: {date}", "---", "",
        f"# {doc['title']}", "",
        f"> Ingested from `{source}` on {date}. AI-extracted text (the original file is unchanged); "
        "each section marks its source page/heading.", "",
    ]
    for pg in doc["pages"]:
        head = pg["heading"] or f"Page {pg['page']}"
        lines += [f"## {head}", "", pg["text"].strip(), ""]
    return "\n".join(lines)


def ingest_file(vault, src_path, config: dict | None = None,
                extract_fn=None, rag=None, router=None) -> dict:
    """Ingest one document → AI/Library/<date>-<slug>.md. Returns a report dict."""
    cfg = config or {}
    report = {"source": str(src_path), "note_path": None, "pages": 0, "chars": 0,
              "format": None, "error": None}
    if not vault:
        report["error"] = "no vault configured"; return report

    # Resolve a vault-relative source path (what the plugin/terminal user types)
    # against the vault; extract_document otherwise treats it as CWD-relative.
    if extract_fn is None:
        sp = Path(src_path)
        if not sp.is_absolute() and not sp.exists():
            cand = Path(vault) / str(src_path)
            if cand.exists():
                src_path = cand
        report["source"] = str(src_path)

        # v1.9 — a .zip of HTML files, or a folder of them, is an interlinked *collection*:
        # import them as a set with inter-file links rewritten to vault wikilinks.
        _sp = Path(src_path)
        if _sp.suffix.lower() == ".zip" or _sp.is_dir():
            from assistant_core.ingest.htmlset import ingest_html_collection
            return ingest_html_collection(vault, src_path, cfg, rag=rag)

    doc = (extract_fn or extract_document)(src_path)
    report["format"] = doc.get("format")
    if not doc.get("ok"):
        report["error"] = doc.get("error") or "extraction produced no text"
        return report

    date = datetime.now().strftime("%Y-%m-%d")
    slug = _slugify(doc["title"] or Path(str(src_path)).stem)
    rel = f"{LIBRARY_DIR}/{date}-{slug}.md"
    out = Path(vault) / rel
    counter = 1
    while out.exists():
        rel = f"{LIBRARY_DIR}/{date}-{slug}-{counter}.md"
        out = Path(vault) / rel
        counter += 1

    note = _build_note(doc, str(src_path), date)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(note, encoding="utf-8")
    report.update(note_path=rel, pages=len(doc["pages"]),
                  chars=sum(len(p["text"]) for p in doc["pages"]))
    logger.info(f"[Ingest] {src_path} → {rel} ({report['pages']} page(s), {report['chars']} chars)")

    # Index immediately if a live RAG service is available (else the watcher will).
    if rag is not None and getattr(rag, "enabled", False):
        try:
            rag.maybe_index_note(rel, note)
        except Exception as exc:
            logger.debug(f"[Ingest] index of {rel} failed: {exc}")

    # Optionally feed the knowledge graph.
    if cfg.get("ingest_to_graph", False) and router is not None:
        try:
            from assistant_core.graph.job import build_graph_for_note
            g = build_graph_for_note(vault, router, rel)
            report["graph_triples"] = g.get("triples", 0)
        except Exception as exc:
            logger.debug(f"[Ingest] graph feed failed: {exc}")
    return report

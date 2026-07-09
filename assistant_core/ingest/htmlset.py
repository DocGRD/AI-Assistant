"""
HTML-collection ingestion — v1.9.

Import a *set* of interlinked HTML files (a `.zip` full of `.htm`/`.html`, or a folder of
them — e.g. a Matthew-Henry commentary export) into the vault as searchable Markdown notes
under `AI/Library/<collection>/`, **rewriting the inter-file links** so they point at the
newly-created vault notes instead of the original `.htm` filenames.

Zero-dependency: uses only the standard library (`zipfile`) plus regex HTML→Markdown, in
keeping with the rest of the codebase (no bs4/markdownify needed). The original file/zip is
never modified. Each note is a normal Markdown file, so the indexer / watcher pick it up.

Link rewriting is two-pass: first map *every* source file → its target note (so we know all
names up front), then convert each file's body, turning any `<a href>` that points at another
file in the set into a path-qualified wikilink `[[AI/Library/<collection>/<slug>|text]]`.
"""

from __future__ import annotations

import html as _html
import logging
import re
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("assistant")

LIBRARY_DIR = "AI/Library"
HTML_EXTS = (".htm", ".html", ".xhtml")

_DROP = re.compile(r"<(script|style|head|nav|header|footer)\b[^>]*>.*?</\1>", re.I | re.S)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
_H1 = re.compile(r"<h1[^>]*>(.*?)</h1>", re.I | re.S)
_A = re.compile(r'<a\b[^>]*?href\s*=\s*["\']([^"\']*)["\'][^>]*>(.*?)</a>', re.I | re.S)
_TAG = re.compile(r"<[^>]+>")


def _slugify(text: str, fallback: str = "page") -> str:
    slug = re.sub(r"[^\w\s-]", "", (text or "").lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")[:60]
    return slug or fallback


def _clean_inline(s: str) -> str:
    """Strip tags + decode entities + collapse whitespace, for inline text (link labels, headings)."""
    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub("", s or ""))).strip()


def extract_title(raw: str, fallback: str = "") -> str:
    m = _TITLE.search(raw) or _H1.search(raw)
    return _clean_inline(m.group(1)) if m and _clean_inline(m.group(1)) else fallback


def html_to_markdown(raw: str, resolve_link=None) -> str:
    """Convert raw HTML to readable Markdown (dependency-free). `resolve_link(href)` returns a
    path-qualified wikilink target (no `.md`) for intra-set links, or None to keep the link as
    an external Markdown link (http/https) or plain text (unresolved local link)."""
    body = _DROP.sub(" ", raw or "")

    def _a_sub(m: re.Match) -> str:
        href, inner = m.group(1).strip(), _clean_inline(m.group(2))
        target = resolve_link(href) if resolve_link else None
        if target:
            return f"[[{target}|{inner}]]" if inner else f"[[{target}]]"
        if href.lower().startswith(("http://", "https://")):
            return f"[{inner or href}]({href})"
        return inner  # unresolved local link → keep the text only

    body = _A.sub(_a_sub, body)
    body = re.sub(r"<h([1-6])[^>]*>(.*?)</h\1>",
                  lambda m: "\n\n" + "#" * int(m.group(1)) + " " + _clean_inline(m.group(2)) + "\n\n",
                  body, flags=re.I | re.S)
    body = re.sub(r"<li[^>]*>(.*?)</li>", lambda m: "\n- " + _clean_inline(m.group(1)), body, flags=re.I | re.S)
    body = re.sub(r"<(b|strong)[^>]*>(.*?)</\1>", lambda m: "**" + _clean_inline(m.group(2)) + "**", body, flags=re.I | re.S)
    body = re.sub(r"<(i|em)[^>]*>(.*?)</\1>", lambda m: "*" + _clean_inline(m.group(2)) + "*", body, flags=re.I | re.S)
    body = re.sub(r"<br\s*/?>", "\n", body, flags=re.I)
    body = re.sub(r"</(p|div|tr|table|ul|ol|blockquote)>", "\n\n", body, flags=re.I)
    body = _TAG.sub("", body)
    body = _html.unescape(body)
    body = re.sub(r"[ \t]+\n", "\n", body)
    body = re.sub(r"[ \t]{2,}", " ", body)
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def _iter_html(root: Path):
    for p in sorted(Path(root).rglob("*")):
        if p.is_file() and p.suffix.lower() in HTML_EXTS:
            yield p


def _build_note(title: str, body_md: str, source: str, collection: str, date: str) -> str:
    return "\n".join([
        "---", "ai-derived: ingested-html", f"source: {source}",
        f"collection: {collection}", f"ingested: {date}", "---", "",
        f"# {title}", "",
        f"> Ingested from `{source}` (collection **{collection}**) on {date}. "
        "Intra-collection links point at the imported vault notes.", "",
        body_md, "",
    ])


def ingest_html_collection(vault, src_path, config: dict | None = None, rag=None) -> dict:
    """Ingest a `.zip` of HTML files, or a folder of them, into AI/Library/<collection>/ with
    inter-file links rewritten to wikilinks. Returns a report dict (never raises)."""
    report = {"source": str(src_path), "format": "html-set", "collection": None,
              "note_dir": None, "note_path": None, "files": 0, "pages": 0,
              "notes": [], "chars": 0, "error": None}
    if not vault:
        report["error"] = "no vault configured"; return report

    src = Path(src_path)
    if not src.is_absolute() and not src.exists() and (Path(vault) / str(src_path)).exists():
        src = Path(vault) / str(src_path)
    report["source"] = str(src)

    tmp: Path | None = None
    try:
        if src.suffix.lower() == ".zip":
            if not src.is_file():
                report["error"] = f"file not found: {src}"; return report
            tmp = Path(tempfile.mkdtemp(prefix="lm_ingest_"))
            root_resolved = tmp.resolve()
            with zipfile.ZipFile(src) as zf:
                for name in zf.namelist():
                    if name.endswith("/"):
                        continue
                    dest = (tmp / name).resolve()
                    if not str(dest).startswith(str(root_resolved)):
                        continue  # zip-slip guard
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with zf.open(name) as fsrc, open(dest, "wb") as fdst:
                        shutil.copyfileobj(fsrc, fdst)
            root, coll_name = tmp, src.stem
        elif src.is_dir():
            root, coll_name = src, src.name
        else:
            report["error"] = f"not a .zip or folder of HTML: {src}"; return report

        files = list(_iter_html(root))
        if not files:
            report["error"] = "no .htm/.html files found"; return report

        collection = _slugify(coll_name, "collection")
        note_dir = f"{LIBRARY_DIR}/{collection}"
        (Path(vault) / note_dir).mkdir(parents=True, exist_ok=True)
        report["collection"], report["note_dir"], report["note_path"] = collection, note_dir, note_dir

        # Pass 1 — assign every source file a unique target note; key by basename for link resolution.
        used: set[str] = set()
        basename_map: dict[str, str] = {}     # "mhc1001.htm" -> "AI/Library/matthew-henry/mhc1001"
        target_of: dict[Path, tuple[str, str]] = {}
        for f in files:
            base = _slugify(f.stem, "page")
            name, i = base, 1
            while name in used:
                i += 1; name = f"{base}-{i}"
            used.add(name)
            target_of[f] = (name, f"{note_dir}/{name}.md")
            basename_map.setdefault(f.name.lower(), f"{note_dir}/{name}")

        def _resolver(href: str):
            h = href.replace("\\", "/").split("#", 1)[0].split("?", 1)[0].strip()
            if not h or h.lower().startswith(("http://", "https://", "mailto:")):
                return None
            return basename_map.get(Path(h).name.lower())

        # Pass 2 — convert + write each note with links rewritten.
        date = datetime.now().strftime("%Y-%m-%d")
        for f in files:
            name, rel = target_of[f]
            raw = f.read_text(encoding="utf-8", errors="replace")
            title = extract_title(raw, f.stem)
            body_md = html_to_markdown(raw, _resolver)
            if not body_md:
                continue
            note = _build_note(title, body_md, str(src), collection, date)
            (Path(vault) / rel).write_text(note, encoding="utf-8")
            report["notes"].append(rel)
            report["chars"] += len(body_md)
            if rag is not None and getattr(rag, "enabled", False):
                try:
                    rag.maybe_index_note(rel, note)
                except Exception as exc:
                    logger.debug(f"[Ingest] index of {rel} failed: {exc}")

        report["files"] = report["pages"] = len(report["notes"])
        logger.info(f"[Ingest] {src} → {note_dir} ({report['files']} note(s), links rewritten)")
        return report
    except Exception as exc:
        report["error"] = f"HTML-collection ingest failed: {exc}"
        return report
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)

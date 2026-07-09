"""
Web clipper — Milestone 40 (D-authoring, capture).

`vault:clip <url>` fetches a page's **readable** text (reusing the keyless M21 web-fetch),
saves it as a clean, sourced note under `AI/Clippings/`, and indexes it so it's immediately
searchable and citeable. Capture-side counterpart to the research/ingest pipeline.

Privacy: only the URL the user asked for is fetched; nothing from the vault is sent out.
"""

from __future__ import annotations

import html as _html
import json as _json
import logging
import re
import urllib.request
from datetime import datetime
from pathlib import Path

from assistant_core.web.fetch import web_fetch

logger = logging.getLogger("assistant")

CLIPPINGS_DIR = "AI/Clippings"
_YT_RE = re.compile(r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/embed/)([A-Za-z0-9_-]{11})")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "clip"


# --- M40 (best-effort) YouTube transcript capture — no heavy deps, urllib only ---

def _is_youtube(url: str) -> bool:
    return bool(_YT_RE.search(url or ""))


def _fetch_raw(url: str, fetch_fn=None) -> str:
    if fetch_fn is not None:
        return fetch_fn(url) or ""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 Loremaster"})
    with urllib.request.urlopen(req, timeout=15) as resp:            # noqa: S310
        return resp.read().decode("utf-8", errors="replace")


def _youtube_capture(url: str, fetch_fn=None) -> dict:
    """Best-effort: pull the caption track URL out of the watch page's player response,
    fetch the transcript XML, and flatten it to text. Degrades gracefully (ok=False)."""
    try:
        page = _fetch_raw(url, fetch_fn)
    except Exception as exc:
        logger.info(f"[clip] youtube page fetch failed: {exc}")
        return {"url": url, "title": "", "text": "", "ok": False}
    tm = re.search(r"<title>(.*?)</title>", page, re.DOTALL)
    title = _html.unescape(tm.group(1)).strip() if tm else url
    m = re.search(r'"captionTracks":(\[.*?\])', page)
    if not m:
        return {"url": url, "title": title, "text": "", "ok": False}
    try:
        tracks = _json.loads(m.group(1).replace("\\u0026", "&"))
    except Exception:
        return {"url": url, "title": title, "text": "", "ok": False}
    track = next((t for t in tracks if str(t.get("languageCode", "")).startswith("en")),
                 tracks[0] if tracks else None)
    if not track or not track.get("baseUrl"):
        return {"url": url, "title": title, "text": "", "ok": False}
    try:
        xml = _fetch_raw(track["baseUrl"].replace("\\u0026", "&"), fetch_fn)
    except Exception as exc:
        logger.info(f"[clip] youtube transcript fetch failed: {exc}")
        return {"url": url, "title": title, "text": "", "ok": False}
    parts = re.findall(r"<text[^>]*>(.*?)</text>", xml, re.DOTALL)
    text = "\n".join(_html.unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in parts if p.strip())
    return {"url": url, "title": title, "text": text, "ok": bool(text.strip())}


def _unique(dest_dir: Path, slug: str) -> str:
    name, n = slug, 2
    while (dest_dir / f"{name}.md").exists():
        name = f"{slug}-{n}"; n += 1
    return name


def clip_url(vault, url: str, rag=None, fetch_fn=None, now: datetime | None = None) -> dict:
    """Clip `url` into AI/Clippings/. Web pages → readable text; YouTube → transcript.
    Returns {ok, path, title, chars, indexed, kind}."""
    now = now or datetime.now()
    yt = _is_youtube(url)
    res = _youtube_capture(url, fetch_fn) if yt else web_fetch(url, fetch_fn=fetch_fn)
    if not res.get("ok"):
        reason = "no transcript available" if yt else "no readable content"
        return {"ok": False, "path": None, "title": "", "chars": 0, "indexed": False,
                "kind": "youtube" if yt else "web", "reason": reason}

    title = (res.get("title") or url).strip()
    text = res.get("text", "").strip()
    dest_dir = Path(vault) / CLIPPINGS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _unique(dest_dir, _slug(title))
    rel = f"{CLIPPINGS_DIR}/{name}.md"

    tags = "[clipping, youtube]" if yt else "[clipping]"
    lede = ("Transcript captured from" if yt else "Clipped from")
    body = (
        f"---\nsource: {res['url']}\nclipped: {now.strftime('%Y-%m-%d %H:%M')}\ntags: {tags}\n---\n\n"
        f"# {title}\n\n"
        f"> {lede} [{res['url']}]({res['url']}) on {now.strftime('%Y-%m-%d')}.\n\n"
        f"{text}\n"
    )
    (Path(vault) / rel).write_text(body, encoding="utf-8")
    logger.info(f"[clip] saved {rel} ({len(text)} chars)")

    indexed = False
    if rag is not None:
        try:
            # index just this one note (never a full vault reindex — that would block).
            if hasattr(rag, "maybe_index_note"):
                indexed = bool(rag.maybe_index_note(rel, body))
            elif hasattr(rag, "index_note"):
                rag.index_note(rel, body)
                indexed = True
            # else: leave it to the file watcher's incremental indexing.
        except Exception as exc:
            logger.info(f"[clip] index skipped: {exc}")

    return {"ok": True, "path": rel, "title": title, "chars": len(text), "indexed": indexed,
            "kind": "youtube" if yt else "web"}

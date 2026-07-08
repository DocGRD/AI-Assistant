"""
Web clipper — Milestone 40 (D-authoring, capture).

`vault:clip <url>` fetches a page's **readable** text (reusing the keyless M21 web-fetch),
saves it as a clean, sourced note under `AI/Clippings/`, and indexes it so it's immediately
searchable and citeable. Capture-side counterpart to the research/ingest pipeline.

Privacy: only the URL the user asked for is fetched; nothing from the vault is sent out.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from assistant_core.web.fetch import web_fetch

logger = logging.getLogger("assistant")

CLIPPINGS_DIR = "AI/Clippings"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60] or "clip"


def _unique(dest_dir: Path, slug: str) -> str:
    name, n = slug, 2
    while (dest_dir / f"{name}.md").exists():
        name = f"{slug}-{n}"; n += 1
    return name


def clip_url(vault, url: str, rag=None, fetch_fn=None, now: datetime | None = None) -> dict:
    """Clip `url` into AI/Clippings/. Returns {ok, path, title, chars, indexed}."""
    now = now or datetime.now()
    res = web_fetch(url, fetch_fn=fetch_fn)
    if not res.get("ok"):
        return {"ok": False, "path": None, "title": "", "chars": 0, "indexed": False}

    title = (res.get("title") or url).strip()
    text = res.get("text", "").strip()
    dest_dir = Path(vault) / CLIPPINGS_DIR
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = _unique(dest_dir, _slug(title))
    rel = f"{CLIPPINGS_DIR}/{name}.md"

    body = (
        f"---\nsource: {res['url']}\nclipped: {now.strftime('%Y-%m-%d %H:%M')}\ntags: [clipping]\n---\n\n"
        f"# {title}\n\n"
        f"> Clipped from [{res['url']}]({res['url']}) on {now.strftime('%Y-%m-%d')}.\n\n"
        f"{text}\n"
    )
    (Path(vault) / rel).write_text(body, encoding="utf-8")
    logger.info(f"[clip] saved {rel} ({len(text)} chars)")

    indexed = False
    if rag is not None:
        try:
            rag.index_note(rel, body) if hasattr(rag, "index_note") else rag.reindex()
            indexed = True
        except Exception as exc:
            logger.info(f"[clip] index skipped: {exc}")

    return {"ok": True, "path": rel, "title": title, "chars": len(text), "indexed": indexed}

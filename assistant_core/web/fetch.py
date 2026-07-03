"""
Web fetch + main-text extraction — Milestone 21, Slice 1.

Fetch a URL and pull out the readable main text. Uses `trafilatura` if installed (best
extraction), otherwise a dependency-free HTML→text fallback (strip script/style/nav,
drop tags, collapse whitespace). The network call is injectable (`fetch_fn`) so tests
never hit the internet, and failures return `{"ok": False}` rather than raising.
"""

from __future__ import annotations

import logging
import re
import urllib.request

logger = logging.getLogger("assistant")

_TITLE_RE  = re.compile(r"<title[^>]*>(.*?)</title>", re.DOTALL | re.IGNORECASE)
_DROP_RE   = re.compile(r"<(script|style|noscript|nav|header|footer|svg)[^>]*>.*?</\1>",
                        re.DOTALL | re.IGNORECASE)
_TAG_RE    = re.compile(r"<[^>]+>")
_WS_RE     = re.compile(r"[ \t]+")
_BLANKS_RE = re.compile(r"\n\s*\n\s*\n+")


def html_to_text(html: str) -> str:
    """Dependency-free readable-text extraction from raw HTML."""
    body = _DROP_RE.sub(" ", html)
    body = re.sub(r"</(p|div|h[1-6]|li|tr|br)>", "\n", body, flags=re.IGNORECASE)
    body = _TAG_RE.sub("", body)
    body = (body.replace("&nbsp;", " ").replace("&amp;", "&")
            .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'")
            .replace("&quot;", '"'))
    body = _WS_RE.sub(" ", body)
    body = _BLANKS_RE.sub("\n\n", body)
    return body.strip()


def _extract(html: str) -> tuple[str, str]:
    """Return (title, main_text). Prefer trafilatura when available."""
    m = _TITLE_RE.search(html)
    title = re.sub(r"\s+", " ", _TAG_RE.sub("", m.group(1))).strip() if m else ""
    try:
        import trafilatura
        extracted = trafilatura.extract(html) or ""
        if extracted.strip():
            return title, extracted.strip()
    except Exception:
        pass
    return title, html_to_text(html)


def web_fetch(url: str, fetch_fn=None, max_chars: int = 12000) -> dict:
    """Fetch `url` → {url, title, text, ok}. `fetch_fn(url)` overrides the network path
    and should return raw HTML (tests). Never raises."""
    url = (url or "").strip()
    if not url.startswith("http"):
        return {"url": url, "title": "", "text": "", "ok": False}
    try:
        if fetch_fn is not None:
            html = fetch_fn(url)
        else:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AI-Assistant"})
            with urllib.request.urlopen(req, timeout=15) as resp:   # noqa: S310
                html = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning(f"[Web] fetch failed for {url}: {exc}")
        return {"url": url, "title": "", "text": "", "ok": False}

    title, text = _extract(html or "")
    return {"url": url, "title": title, "text": text[:max_chars], "ok": bool(text.strip())}

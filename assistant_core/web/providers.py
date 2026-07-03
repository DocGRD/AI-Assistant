"""
Web-search providers — Milestone 21.

Like the model registry, search is **config-driven and free-first**: an ordered list of
providers is tried until one returns results, and any provider whose key/URL isn't set is
skipped — so out of the box it costs nothing (keyless DuckDuckGo, or a self-hosted
SearXNG). Add a key in settings and that provider joins the rotation; reorder with
`web_search_order`. Each adapter returns `[{title, url, snippet}]` and may raise — the
caller (`web_search`) catches and falls through to the next provider.

Free tiers (as advertised): DuckDuckGo (keyless), SearXNG (self-host, keyless),
Brave (~1k/mo), Serper (2.5k signup), Tavily (1k/mo, AI-native), Exa (1k/mo, semantic),
Google CSE (100/day).
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
import urllib.request

logger = logging.getLogger("assistant")

_UA = {"User-Agent": "Mozilla/5.0 AI-Assistant"}
_DDG_HTML = "https://html.duckduckgo.com/html/"
_RESULT_RE = re.compile(r'result__a[^>]*href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>', re.DOTALL | re.I)
_SNIPPET_RE = re.compile(r'result__snippet[^>]*>(?P<snip>.*?)</a>', re.DOTALL | re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _strip(html: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub("", html)).strip()


def _get(url: str, headers: dict | None = None, timeout: int = 15) -> str:
    req = urllib.request.Request(url, headers={**_UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310
        return r.read().decode("utf-8", errors="replace")


def _post_json(url: str, body: dict, headers: dict | None = None, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json", **_UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _decode_ddg(href: str) -> str:
    """Unwrap DDG's //duckduckgo.com/l/?uddg=<encoded-url> redirect."""
    if "uddg=" in href:
        q = urllib.parse.urlparse(("https:" + href) if href.startswith("//") else href).query
        val = urllib.parse.parse_qs(q).get("uddg", [""])[0]
        if val:
            return urllib.parse.unquote(val)
    return ("https:" + href) if href.startswith("//") else href


def _ddg_html(query: str, k: int) -> list[dict]:
    data = urllib.parse.urlencode({"q": query}).encode()
    req = urllib.request.Request(_DDG_HTML, data=data, headers=_UA)
    with urllib.request.urlopen(req, timeout=15) as resp:   # noqa: S310
        html = resp.read().decode("utf-8", errors="replace")
    titles, snips = list(_RESULT_RE.finditer(html)), list(_SNIPPET_RE.finditer(html))
    out = []
    for i, m in enumerate(titles[:k]):
        url = _decode_ddg(m.group("href"))
        if url.startswith("http"):
            out.append({"title": _strip(m.group("title")), "url": url,
                        "snippet": _strip(snips[i].group("snip")) if i < len(snips) else ""})
    return out


# ── adapters: (query, k, config) -> [{title, url, snippet}] ─────────────────

def duckduckgo(query, k, config):
    """Keyless. Prefer the ddgs/duckduckgo_search library; fall back to HTML scrape."""
    DDGS = None
    for mod in ("ddgs", "duckduckgo_search"):
        try:
            DDGS = __import__(mod, fromlist=["DDGS"]).DDGS
            break
        except Exception:
            continue
    if DDGS is not None:
        with DDGS() as d:
            return [{"title": r.get("title", ""), "url": r.get("href", ""),
                     "snippet": r.get("body", "")} for r in d.text(query, max_results=k)][:k]
    return _ddg_html(query, k)


def searxng(query, k, config):
    base = str(config.get("searxng_url", "")).rstrip("/")
    data = json.loads(_get(f"{base}/search?q={urllib.parse.quote(query)}&format=json"))
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in data.get("results", []) if r.get("url")][:k]


def brave(query, k, config):
    data = json.loads(_get(
        f"https://api.search.brave.com/res/v1/web/search?q={urllib.parse.quote(query)}&count={k}",
        headers={"X-Subscription-Token": config.get("brave_api_key", ""), "Accept": "application/json"}))
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("description", "")}
            for r in data.get("web", {}).get("results", [])][:k]


def serper(query, k, config):
    data = _post_json("https://google.serper.dev/search", {"q": query, "num": k},
                      {"X-API-KEY": config.get("serper_api_key", "")})
    return [{"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
            for r in data.get("organic", [])][:k]


def tavily(query, k, config):
    data = _post_json("https://api.tavily.com/search",
                      {"api_key": config.get("tavily_api_key", ""), "query": query, "max_results": k})
    return [{"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("content", "")}
            for r in data.get("results", []) if r.get("url")][:k]


def exa(query, k, config):
    data = _post_json("https://api.exa.ai/search",
                      {"query": query, "numResults": k, "contents": {"text": True}},
                      {"x-api-key": config.get("exa_api_key", "")})
    return [{"title": r.get("title", ""), "url": r.get("url", ""),
             "snippet": (r.get("text", "") or "")[:300]} for r in data.get("results", []) if r.get("url")][:k]


def google_cse(query, k, config):
    key, cx = config.get("google_search_api_key", ""), config.get("google_cse_id", "")
    data = json.loads(_get(
        f"https://www.googleapis.com/customsearch/v1?key={key}&cx={cx}"
        f"&q={urllib.parse.quote(query)}&num={min(k, 10)}"))
    return [{"title": r.get("title", ""), "url": r.get("link", ""), "snippet": r.get("snippet", "")}
            for r in data.get("items", [])][:k]


# name -> (adapter, is-configured predicate). Keyless providers are always ready.
PROVIDERS = {
    "duckduckgo": (duckduckgo, lambda c: True),
    "searxng":    (searxng,    lambda c: bool(str(c.get("searxng_url", "")).strip())),
    "brave":      (brave,      lambda c: bool(str(c.get("brave_api_key", "")).strip())),
    "serper":     (serper,     lambda c: bool(str(c.get("serper_api_key", "")).strip())),
    "tavily":     (tavily,     lambda c: bool(str(c.get("tavily_api_key", "")).strip())),
    "exa":        (exa,        lambda c: bool(str(c.get("exa_api_key", "")).strip())),
    "google":     (google_cse, lambda c: bool(str(c.get("google_search_api_key", "")).strip()
                                              and str(c.get("google_cse_id", "")).strip())),
}
DEFAULT_ORDER = ["duckduckgo", "searxng", "brave", "serper", "tavily", "exa", "google"]

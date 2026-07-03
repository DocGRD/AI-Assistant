"""
Web search — Milestone 21.

Config-driven, free-first: try providers in `web_search_order` until one returns results,
skipping any whose key/URL isn't configured (see `web/providers.py`). Keyless DuckDuckGo
is the default, so it costs nothing out of the box; adding a key enrolls that provider.
The network path is injectable (`search_fn`) for tests, and every path degrades to `[]`
rather than raising — a failed search must not break a turn.

Returns `[{title, url, snippet}]`.
"""

from __future__ import annotations

import logging

from assistant_core.web.providers import PROVIDERS, DEFAULT_ORDER, _decode_ddg  # noqa: F401 (re-export)

logger = logging.getLogger("assistant")


def web_search(query: str, k: int = 5, config: dict | None = None, search_fn=None) -> list[dict]:
    """Search the web → [{title, url, snippet}]. `search_fn(query, k)` overrides the
    network path (tests). Tries each configured provider in order; never raises."""
    query = (query or "").strip()
    if not query:
        return []
    if search_fn is not None:
        try:
            return list(search_fn(query, k))
        except Exception as exc:
            logger.warning(f"[Web] injected search_fn failed: {exc}")
            return []

    cfg = config or {}
    order = cfg.get("web_search_order") or DEFAULT_ORDER
    tried = []
    for name in order:
        entry = PROVIDERS.get(name)
        if entry is None:
            continue
        fn, ready = entry
        if not ready(cfg):
            continue
        tried.append(name)
        try:
            results = fn(query, k, cfg)
            if results:
                logger.info(f"[Web] search via {name}: {len(results)} result(s) for {query!r}")
                return results[:k]
        except Exception as exc:
            logger.warning(f"[Web] provider {name} failed: {exc}")
    if tried:
        logger.info(f"[Web] no results for {query!r} (tried: {', '.join(tried)})")
    return []

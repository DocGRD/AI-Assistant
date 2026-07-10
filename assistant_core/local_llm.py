"""
Local small-model helper — v1.9.7.

A tiny, dependency-free client for a **local** OpenAI-compatible LLM (Ollama by default:
`http://127.0.0.1:11434/v1`). It is used ONLY for *reductive* internal tasks — right now
compressing/summarising old chat turns in the ContextManager — where a small model is safe
(it condenses text that's already in the prompt; it never recalls from memory, so it can't
fabricate facts). User-facing answers still go to the curated cloud models via the router.

Why this matters: the context-compression summary used to go through the router → a cloud
provider (burning free-tier tokens, adding a network round-trip, and hitting the same rate
limits). A ~3B local model does this job for free, offline, instantly, and privately.

Auto-enabled: if Ollama answers on the box, summarisation switches to it; if not, everything
falls back to the previous behaviour. Availability is probed with a short cache so we don't
hit the socket on every request.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.request

logger = logging.getLogger("assistant")

DEFAULT_MODEL = "qwen2.5:3b"
DEFAULT_BASE_URL = "http://127.0.0.1:11434/v1"

_avail_cache = {"checked": 0.0, "ok": False}
_AVAIL_TTL = 60.0  # seconds


def _base_url(config: dict | None) -> str:
    return ((config or {}).get("local_base_url") or DEFAULT_BASE_URL).rstrip("/")


def model_name(config: dict | None) -> str:
    return (config or {}).get("local_model") or DEFAULT_MODEL


def available(config: dict | None = None, *, force: bool = False) -> bool:
    """True if a local OpenAI-compatible server (Ollama) is reachable. Cached for a minute."""
    if (config or {}).get("local_model") == "off":
        return False
    now = time.time()
    if not force and (now - _avail_cache["checked"]) < _AVAIL_TTL:
        return _avail_cache["ok"]
    ok = False
    try:
        # Ollama's native tags endpoint (base is .../v1 → strip to host root)
        root = _base_url(config).rsplit("/v1", 1)[0]
        req = urllib.request.Request(f"{root}/api/tags")
        with urllib.request.urlopen(req, timeout=1.5) as resp:   # noqa: S310 (localhost)
            ok = resp.status == 200
    except Exception:
        ok = False
    _avail_cache.update(checked=now, ok=ok)
    return ok


def complete(prompt: str, system: str, config: dict | None = None,
             max_tokens: int = 300, temperature: float = 0.3, timeout: int = 60) -> str | None:
    """One chat completion from the local model. Returns text, or None on any failure."""
    body = json.dumps({
        "model": model_name(config),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }).encode("utf-8")
    try:
        req = urllib.request.Request(f"{_base_url(config)}/chat/completions", data=body,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310 (localhost)
            data = json.loads(resp.read().decode("utf-8"))
        return (data["choices"][0]["message"]["content"] or "").strip() or None
    except Exception as exc:
        logger.warning(f"[LocalLLM] completion failed: {exc}")
        _avail_cache["checked"] = 0.0   # re-probe next time
        return None


def summarize(text: str, config: dict | None = None) -> str | None:
    """Condense a span of conversation into a few factual sentences (reductive → low-risk)."""
    system = ("Summarise the conversation below into a few sentences that capture the decisions "
              "made, facts established, and any open threads. Be concise and strictly factual — "
              "only use what is written here; do not add anything. This replaces the raw turns in "
              "the assistant's working memory.")
    return complete(text[:6000], system, config, max_tokens=300, temperature=0.2)

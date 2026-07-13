"""
Map-reduce summarization for oversized content.

When the agent reads a huge note/file (e.g. a 100 KB Project-State.md), dumping it whole into
context overflows every free provider. Blind head+tail truncation loses the middle. This module
does what a human skim-reader does instead: **chunk → summarize each chunk → summarize the
summaries** (recursively until it fits), which retains key points far better than truncation.

Zero-cost first: it prefers the local model (Ollama qwen2.5:3b) for the per-chunk summaries; if
that's unavailable it uses the router (private-safe), and if NO summarizer is reachable it
degrades gracefully to head+tail truncation so a request always fits.
"""

from __future__ import annotations

import logging

from assistant_core.editing import split_for_edit

logger = logging.getLogger("assistant")

_CHUNK_CHARS = 6000        # ~1500 tokens/chunk — safe for even the smallest models
_MAX_LEVELS = 3            # recursion cap (summarize-the-summaries), so it always terminates

_SYSTEM = ("You compress text. Output a tight, faithful summary that preserves concrete facts, "
           "names, dates, numbers, file paths, and decisions verbatim where possible. No preamble, "
           "no opinions, no 'this text discusses' filler — just the substance.")


def _truncate(text: str, target_chars: int) -> str:
    """Head+tail truncation with a marker — the last-resort fallback."""
    if len(text) <= target_chars:
        return text
    marker = "\n\n… [truncated] …\n\n"
    keep = max(200, target_chars - len(marker))
    head_n = int(keep * 0.6)
    return text[:head_n] + marker + text[-(keep - head_n):]


def _summarize_one(text: str, router, config: dict, focus: str) -> str | None:
    """Summarize a single chunk. Local model first (free), then the router. None on failure."""
    focus_line = f"Keep everything relevant to this question: {focus}\n\n" if focus else ""
    prompt = f"{focus_line}Summarize the following, preserving key specifics:\n\n{text}"
    try:
        from assistant_core import local_llm
        if local_llm.available(config):
            out = local_llm.complete(prompt, _SYSTEM, config)
            if out and out.strip():
                return out.strip()
    except Exception as exc:
        logger.debug(f"[Summarize] local model failed: {exc}")
    if router is not None and getattr(router, "available_providers", None):
        try:
            from assistant_core.providers.base_provider import Message
            reply, _ = router.generate([Message(role="user", content=prompt)],
                                       system_prompt=_SYSTEM, task="extract",
                                       private=True, allow_webui=False)
            if reply and reply.strip():
                return reply.strip()
        except Exception as exc:
            logger.debug(f"[Summarize] router summarize failed: {exc}")
    return None


def map_reduce_summarize(text: str, router=None, config: dict | None = None,
                         target_chars: int = 6000, focus: str = "") -> str:
    """Condense `text` to ~target_chars via chunk→summarize→(recurse). `focus` (e.g. the user's
    question) steers each chunk summary to keep relevant points. Always returns text that fits."""
    text = text or ""
    if len(text) <= target_chars:
        return text
    config = config or {}
    current = text
    for _ in range(_MAX_LEVELS):
        chunks = split_for_edit(current, max_chars=_CHUNK_CHARS)
        if len(chunks) <= 1:
            break
        summaries = []
        shrank = False
        for c in chunks:
            s = _summarize_one(c, router, config, focus)
            if s and len(s) < len(c):
                shrank = True
                summaries.append(s)
            else:
                summaries.append(_truncate(c, max(400, _CHUNK_CHARS // 3)))
        current = "\n\n".join(summaries)
        if len(current) <= target_chars:
            return current
        if not shrank:            # summarizer isn't actually reducing size — stop looping
            break
    if len(current) > target_chars:
        s = _summarize_one(current, router, config, focus)
        current = s if (s and len(s) <= target_chars) else _truncate(current, target_chars)
    return current

"""
Research round-trip helper — Milestone 20 (hardened after T5.01).

When a web-AI research response is pasted back we:
  1. save it VERBATIM (full text + citations always land intact), then
  2. summarise it with ONE non-agentic LLM call (no tool execution), then
  3. append a "## Related notes" section built DETERMINISTICALLY from the local index.

Critically, the summary call does **not** run the agent loop. T5.01 showed that letting
the model "search the vault and add related links" made it invent note paths (hallucinated
wikilinks) and loop on repeated searches. Real related notes come from `rag.relevant_notes`
(actual index neighbours) — never from the model. Shared by the server (`/chat/handoff-return`)
and the terminal so both behave identically.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger("assistant")

_SUMMARY_SYSTEM = (
    "You are summarising research that has ALREADY been saved to a note. In 2-3 sentences, "
    "give the user a clear, plain-English summary of the findings for their question. Output "
    "ONLY the summary — no headings, no bullet lists, no wikilinks, no vault: commands, and no "
    "offer to do more. Do not invent sources or note names."
)

_TITLE_SYSTEM = (
    "Read the text and give it a short, specific title suitable as a note filename: "
    "1 to 4 words, Title Case, no punctuation, no quotation marks, no trailing period, "
    "and do not use the words 'Research' or 'Notes'. Output ONLY the title — nothing else."
)


def save_research_verbatim(registry, research_text: str) -> str | None:
    """Save the pasted research as-is via import_research. Returns the saved path or None."""
    if not registry:
        return None
    imp = registry.run("import_research", research_text)
    if getattr(imp, "success", False):
        return (getattr(imp, "metadata", None) or {}).get("path")
    return None


def summarize_research(router, original: str, research_text: str, private: bool = False) -> str:
    """ONE non-agentic call → a 2-3 sentence summary. No tools, so no hallucinated links
    and no loop. Returns '' on failure (caller still has the saved note)."""
    if router is None:
        return ""
    from assistant_core.providers.base_provider import Message
    msg = f"Question: {original}\n\nResearch:\n{research_text[:6000]}"
    try:
        reply, _ = router.generate(
            messages=[Message(role="user", content=msg)],
            system_prompt=_SUMMARY_SYSTEM, max_tokens=250, temperature=0.3,
            private=private, allow_webui_on_private=False,
        )
        return (reply or "").strip()
    except Exception as exc:
        logger.warning(f"[Research] summary call failed: {exc}")
        return ""


def generate_note_title(router, content: str) -> str | None:
    """ONE non-agentic call → a short 1-4 word title for a note (used for both the
    filename slug and the H1 heading). No tools, so it can't loop or invent vault
    content — worst case it returns a bad title, never a fabricated action. Forces
    PRIVATE routing (no-train providers only): the caller's privacy context isn't known
    at this layer, so this errs safe rather than risk leaking a snippet to a training
    provider just to name a note. Returns None on failure/empty (caller falls back to
    the existing heuristic slug)."""
    if router is None:
        return None
    from assistant_core.providers.base_provider import Message
    try:
        reply, _ = router.generate(
            messages=[Message(role="user", content=content[:1500])],
            system_prompt=_TITLE_SYSTEM, max_tokens=20, temperature=0.3,
            private=True, allow_webui_on_private=False,
        )
    except Exception as exc:
        logger.warning(f"[Research] title call failed: {exc}")
        return None
    title = (reply or "").strip().strip('"').strip("'").strip(".").strip()
    if not title:
        return None
    return " ".join(title.split()[:4]) or None


def append_related_notes(rag, vault_path, saved_path: str, k: int = 5) -> list[str]:
    """Append a '## Related notes' section of REAL index neighbours to the saved note.
    Returns the linked note paths (empty if RAG is unavailable or nothing is similar) —
    never fabricates a link."""
    if not saved_path or rag is None or not getattr(rag, "enabled", False):
        return []
    try:
        related = rag.relevant_notes(saved_path, k=k)
    except Exception as exc:
        logger.warning(f"[Research] relevant_notes failed: {exc}")
        return []
    paths = [r["path"] for r in related if r.get("path") and r["path"] != saved_path]
    if not paths:
        return []
    note = Path(vault_path) / saved_path
    links = [f"- [[{p[:-3] if p.endswith('.md') else p}]]" for p in paths]
    try:
        with open(note, "a", encoding="utf-8") as fh:
            fh.write("\n## Related notes\n\n" + "\n".join(links) + "\n")
    except Exception as exc:
        logger.warning(f"[Research] could not append related notes: {exc}")
        return []
    return paths

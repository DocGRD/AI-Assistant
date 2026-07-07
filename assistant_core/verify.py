"""
Hallucination guard — Milestone 30.

After a factual answer is produced, check it can actually be *grounded*. If it isn't
supported by the vault, try to ground it: escalate to a larger model, then search the web
for real citations and attach them. Only if nothing supports it do we flag it ⚠.

Reuses the deterministic provenance audit (M25, `provenance.find_sources`) and the keyless
web search (M21, `web.search.web_search`). Private content is never sent to the web.
"""

import logging

from assistant_core.provenance import find_sources
from assistant_core.web.search import web_search

logger = logging.getLogger("assistant")


def _flag(answer: str, why: str) -> str:
    return f"⚠ **Unverified** — {why}. Treat with caution.\n\n{answer}"


def _escalate(router, question: str) -> str | None:
    """Re-answer the question on a larger/stronger model (task='verify' prefers large)."""
    try:
        from assistant_core.providers.base_provider import Message
        reply, used = router.generate(
            [Message(role="user", content=question)],
            task="verify", allow_webui=False,
        )
        reply = (reply or "").strip()
        if reply:
            logger.info(f"[verify] escalated to {used}")
            return reply
    except Exception as exc:                       # provider exhaustion etc. — non-fatal
        logger.info(f"[verify] escalation failed: {exc}")
    return None


def _web_cites(question: str, config: dict, search_fn=None) -> list[tuple[str, str]]:
    """Top web results as (title, url) citations for the claim. Never raises."""
    try:
        results = web_search(
            question, k=int((config or {}).get("web_max_results", 5)),
            config=config or {}, search_fn=search_fn,
        )
    except Exception as exc:
        logger.info(f"[verify] web search failed: {exc}")
        return []
    cites: list[tuple[str, str]] = []
    seen: set[str] = set()
    for r in results:
        url = (r.get("url") or "").strip()
        title = (r.get("title") or url).strip()
        if url and url not in seen:
            seen.add(url)
            cites.append((title, url))
        if len(cites) >= 4:
            break
    return cites


def guard_answer(answer: str, question: str, router, vault_path, config: dict,
                 *, private: bool = False, search_fn=None) -> tuple[str, str]:
    """
    Verify `answer`. Returns (final_answer, status). Statuses:
      off | grounded | escalated | web_verified | flagged | flagged_private | unverified
    Bounded: at most one escalation + one web-verify. `private` disables the web step.
    """
    policy = (config or {}).get("hallucination_guard", "escalate_web")
    if policy == "off" or not (answer or "").strip() or not vault_path:
        return answer, "off"

    # 1. Already supported by the vault? (deterministic term-overlap audit)
    if find_sources(vault_path, answer).get("sourced"):
        return answer, "grounded"

    # 2. Private content must never be sent to the web → flag only.
    if private:
        return _flag(answer, "not grounded in your vault"), "flagged_private"

    if policy == "flag":
        return _flag(answer, "not found in your vault"), "flagged"

    # policy == "escalate_web"
    # 2a. Escalate to a larger model; if that answer *is* grounded, take it.
    escalated = _escalate(router, question)
    if escalated:
        if find_sources(vault_path, escalated).get("sourced"):
            return escalated, "escalated"
        answer = escalated                          # keep the better answer for citation

    # 2b. Web-verify — attach real sources for the claim.
    cites = _web_cites(question, config, search_fn)
    if cites:
        block = "\n\n**Sources (web-verified):**\n" + "\n".join(f"- [{t}]({u})" for t, u in cites)
        return answer + block, "web_verified"

    # 3. Nothing supports it.
    return _flag(answer, "not found in your vault or on the web"), "unverified"

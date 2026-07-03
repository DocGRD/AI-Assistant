"""
Autonomous web research — Milestone 21, Slices 2-4.

Turns a question into a saved, cited research note WITHOUT the manual paste round-trip:
search → fetch the top pages → synthesise (ONE non-agentic call, citing only fetched
URLs) → save each page **verbatim** plus a summary note under `AI/Research/<date>-<slug>/`
→ append real related notes from the index.

Privacy is hard-blocked: a `private` turn never touches the web, and only the query
string ever leaves the machine (never vault content). Everything is bounded
(`web_max_results` / `web_max_fetches`) and degrades gracefully — the manual
`vault:research` round-trip remains the fallback.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from assistant_core.web.search import web_search
from assistant_core.web.fetch import web_fetch

logger = logging.getLogger("assistant")


def _slugify(text: str) -> str:
    slug = re.sub(r"[^\w\s-]", "", (text or "").lower())
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug[:40]


def _synthesise(router, query: str, fetched: list[dict]) -> str:
    if router is None:
        return ""
    from assistant_core.providers.base_provider import Message
    blocks = [f"[{i}] {p['title'] or p['url']} — {p['url']}\n{p['text'][:2500]}"
              for i, p in enumerate(fetched, 1)]
    corpus = "\n\n".join(blocks)[:9000]
    sys = ("Synthesise the numbered web sources below into a clear, well-structured answer to the "
           "user's question. Cite sources inline as [n], using ONLY the provided sources. Do NOT "
           "invent facts, sources, or URLs. If the sources are thin or disagree, say so plainly.")
    try:
        reply, _ = router.generate(
            messages=[Message(role="user", content=f"Question: {query}\n\nSources:\n{corpus}")],
            system_prompt=sys, max_tokens=800, temperature=0.3,
            private=False, allow_webui_on_private=False)
        return (reply or "").strip()
    except Exception as exc:
        logger.warning(f"[Web] synthesis call failed: {exc}")
        return ""


def run_web_research(query: str, router, config: dict, rag=None, private: bool = False,
                     search_fn=None, fetch_fn=None) -> dict:
    """Search + fetch + synthesise + save. Returns a report dict."""
    report = {"query": query, "sources": [], "summary_path": None, "folder": None,
              "related": [], "error": None}
    query = (query or "").strip()
    if not query:
        report["error"] = "empty query"; return report
    if private:
        report["error"] = "web research is disabled for private turns"; return report
    cfg = config or {}
    if not cfg.get("web_research_enabled", True):
        report["error"] = "web research is disabled (web_research_enabled=false)"; return report
    vault = cfg.get("vault_path")
    if not vault:
        report["error"] = "no vault configured"; return report

    results = web_search(query, k=int(cfg.get("web_max_results", 5)), config=cfg, search_fn=search_fn)
    if not results:
        report["error"] = "no web results (search unavailable or blocked)"; return report

    fetched = []
    for r in results[: int(cfg.get("web_max_fetches", 4))]:
        page = web_fetch(r["url"], fetch_fn=fetch_fn)
        if page["ok"]:
            page["title"] = page["title"] or r.get("title", "")
            fetched.append(page)
    if not fetched:
        report["error"] = "could not fetch any result pages"; return report

    synthesis = _synthesise(router, query, fetched)

    from assistant_core.research_roundtrip import generate_note_title, append_related_notes
    title = (generate_note_title(router, synthesis or query) or query)[:60]
    date  = datetime.now().strftime("%Y-%m-%d")
    base  = f"AI/Research/{date}-{_slugify(title) or 'web-research'}"
    folder = Path(vault) / base
    folder.mkdir(parents=True, exist_ok=True)

    # Save each fetched page verbatim, and build citation links.
    src_links = []
    for i, page in enumerate(fetched, 1):
        (folder / f"Source-{i}.md").write_text(
            f"---\nai-derived: web-source\nurl: {page['url']}\nfetched: {date}\n---\n\n"
            f"# {page['title'] or page['url']}\n\n<{page['url']}>\n\n---\n\n{page['text']}\n",
            encoding="utf-8")
        report["sources"].append({"n": i, "url": page["url"], "title": page["title"],
                                  "file": f"{base}/Source-{i}.md"})
        src_links.append(f"{i}. [{page['title'] or page['url']}]({page['url']}) — [[Source-{i}]]")

    summary_md = (
        f"---\nai-derived: web-research\nquery: {query}\ngenerated: {date}\n---\n\n"
        f"# {title}\n\n> Autonomous web research for *{query}*. Sources were fetched and saved "
        f"verbatim in this folder; citations link to them.\n\n"
        f"{synthesis or '(no synthesis available)'}\n\n## Sources\n\n" + "\n".join(src_links) + "\n")
    (folder / "Summary.md").write_text(summary_md, encoding="utf-8")
    report["summary_path"] = f"{base}/Summary.md"
    report["folder"] = base
    report["related"] = append_related_notes(rag, vault, f"{base}/Summary.md")
    logger.info(f"[Web] research saved: {report['summary_path']} ({len(fetched)} source(s))")
    return report

"""
Extended vault: command dispatch — Milestone 33.

The agent loop's built-in command table (`agent_loop.VAULT_COMMANDS`) only covers the
basic read/write tools. The *rich* commands — autonomous web research, ingest, OCR,
graph, structured query, provenance, scripture, flashcards — existed ONLY as
server/terminal intercepts the agent could not reach, so "look on the web for X" fell
back to the paste-into-a-web-AI handoff (`vault:research`) instead of the autonomous
`vault:webresearch`.

`run_extended` gives the agent loop those same handlers (reusing the existing functions).
Each result is classified:
  - inject=True  → feed the result back so the agent presents/uses it (research, query…)
  - terminal=True → the result IS the answer; end the turn (ingest, ocr, cards…)
Privacy is honored: web research is refused on a private turn.
"""

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("assistant")

# Commands handled here (everything the agent may run beyond agent_loop.VAULT_COMMANDS).
EXTENDED_COMMANDS = {
    "vault:webresearch", "vault:ingest", "vault:ocr", "vault:analyze", "vault:graph",
    "vault:graph-merge", "vault:guide", "vault:query", "vault:sources", "vault:passage",
    "vault:transcribe", "vault:cards", "vault:review", "vault:logs", "vault:consolidate",
    "vault:goal",
}


@dataclass
class ExtResult:
    output:   str
    success:  bool = True
    terminal: bool = False   # True → output IS the answer; loop ends


def run_extended(prefix: str, arg: str, ctx) -> "ExtResult | None":
    """Run a rich command for the agent loop. Returns None if `prefix` isn't ours."""
    prefix = prefix.lower()
    if prefix not in EXTENDED_COMMANDS:
        return None
    vault   = (ctx.config or {}).get("vault_path")
    router  = ctx.router
    rag     = getattr(ctx, "rag", None)
    private = bool(getattr(ctx, "private", False))
    arg     = (arg or "").strip()

    try:
        if prefix == "vault:webresearch":
            if private:
                return ExtResult("Web research is disabled on a private turn (it would send "
                                 "content to the web). Answer from the vault, or the user can "
                                 "re-ask without privacy.", success=False, terminal=True)
            if not arg:
                return ExtResult("Usage: vault:webresearch <question>", success=False, terminal=True)
            from assistant_core.web.research import run_web_research
            rep = run_web_research(arg, router, ctx.config, rag=rag, private=False)
            if rep.get("error"):
                return ExtResult(f"Web research could not run: {rep['error']}.", success=False, terminal=True)
            summary = ""
            try:
                sp = Path(vault) / rep["summary_path"]
                summary = _strip_frontmatter(sp.read_text(encoding="utf-8"))
            except Exception:
                pass
            _episode(ctx, "webresearch", arg[:80])
            out = (f"Autonomous web research complete — saved to {rep['summary_path']} "
                   f"({len(rep['sources'])} source(s)). Findings:\n\n{summary}")
            return ExtResult(out)   # inject → agent presents the findings

        if prefix == "vault:sources":
            from assistant_core.provenance import find_sources
            if not arg:
                return ExtResult("Usage: vault:sources <claim>", success=False, terminal=True)
            rep = find_sources(vault, arg)
            if not rep["sources"]:
                return ExtResult("⚠ Unsourced — no notes contain these terms.")
            tag = "" if rep["sourced"] else "⚠ Weakly sourced.\n\n"
            return ExtResult(tag + "Supporting notes:\n" + "\n".join(
                f"- {s['path']} ({s['matched']}/{s['of']} terms)" for s in rep["sources"]))

        if prefix == "vault:query":
            from assistant_core.query import structured_search
            if not arg:
                return ExtResult('Usage: vault:query tag:sermon "phrase" path:"06 - Projects"',
                                 success=False, terminal=True)
            hits = structured_search(vault, arg)
            return ExtResult(f"No notes match `{arg}`." if not hits else
                             f"{len(hits)} note(s) match `{arg}`:\n" + "\n".join(f"- {h['path']}" for h in hits))

        if prefix == "vault:logs":
            # v1.9 — self-diagnosis: read the service's own logs (outside the vault).
            from assistant_core import logs_reader
            return ExtResult(logs_reader.format_reply(logs_reader.read_logs(arg)), terminal=True)

        if prefix == "vault:goal":
            # When the user explicitly asks to set/plan a goal, the agent emits `vault:goal <desc>`.
            # PROPOSE-ONLY: this plans a multi-step goal and stages it for approval — it does NOT run
            # until the user approves in the 🎯 Goals panel. Control verbs stay the user's, not the agent's.
            verb = (arg.split(None, 1)[0].lower() if arg else "")
            if not arg or verb in {"approve", "pause", "resume", "cancel", "replan", "list", "goals"}:
                return ExtResult(
                    "To create a goal, emit `vault:goal <description>` — it plans the goal and stages it "
                    "for the user to approve in the 🎯 Goals panel (it does not run until approved). "
                    "Approving, pausing, or cancelling a goal is the user's action, not yours.",
                    success=False, terminal=True)
            from assistant_core.goals.planner import plan_goal, plan_from_template, detect_template
            from assistant_core.goals import store as gstore
            tmpl = detect_template(arg) or ""
            desc = arg
            if tmpl:
                parts = arg.split(None, 1)
                desc = parts[1] if len(parts) > 1 else arg
            try:
                plan = plan_from_template(tmpl, desc) if tmpl else None
                if plan is None:
                    plan = plan_goal(arg, router, private=private)
            except Exception as exc:
                return ExtResult(f"Could not plan that goal: {exc}", success=False, terminal=True)
            if not plan.get("subtasks"):
                return ExtResult("Could not plan that goal — try rephrasing it.", success=False, terminal=True)
            g = gstore.create_goal(arg, plan["subtasks"], plan.get("estimate", ""),
                                   template=plan.get("template", ""))
            try:
                gstore.render_note(vault, g)
            except Exception:
                pass
            _episode(ctx, "goal_planned", g.get("slug", ""))
            steps = "\n".join(f"{i+1}. {s}" for i, s in enumerate(plan["subtasks"]))
            return ExtResult(
                f"**Planned goal** `{g['slug']}` — {plan.get('estimate', '')}\n\n{steps}\n\n"
                f"Approve it to run in the background from the **🎯 Goals** panel "
                f"(or `vault:goal approve {g['slug']}`).",
                terminal=True)

        if prefix == "vault:consolidate":
            # M44 — on-demand memory consolidation ("dreaming"). PROPOSE-ONLY: extracts durable
            # facts from recent episodes into a review note + the 📥 Approvals inbox; nothing is
            # saved to Learned-Facts until the user approves. (Also runs nightly on its own.)
            from assistant_core.consolidation import ConsolidationEngine
            embedder = rag.embedder if (rag and getattr(rag, "enabled", False)) else None
            try:
                rep = ConsolidationEngine(vault, router, embedder).run(apply=False)
            except Exception as exc:
                return ExtResult(f"Memory consolidation could not run: {exc}", success=False, terminal=True)
            _episode(ctx, "consolidate", f"{len(rep.get('new_facts', []))} facts")
            if not rep.get("proposal"):
                return ExtResult("Memory consolidation ran — no new durable facts to propose "
                                 "(no new episodes since the last run).", terminal=True)
            return ExtResult(
                f"Memory consolidation complete — proposed **{len(rep['new_facts'])} durable "
                f"fact(s)** from {len(rep.get('days', []))} day(s) of activity. Review and approve "
                f"them in the **📥 Approvals** inbox (memory items) — nothing is saved to "
                f"Learned-Facts until you approve. (Proposal note: `{rep['proposal']}`.)",
                terminal=True)

        if prefix == "vault:passage":
            from assistant_core.scripture.passage import build_passage_guide
            if not arg:
                return ExtResult("Usage: vault:passage <e.g. 1 John 2:18-20>", success=False, terminal=True)
            rep = build_passage_guide(vault, router, arg, rag=rag)
            if rep.get("error"):
                return ExtResult(rep["error"], success=False)
            _episode(ctx, "passage", arg[:80])
            notes = f"\n\n*Notes: {', '.join(rep['notes'][:8])}*" if rep.get("notes") else ""
            return ExtResult(f"**Passage: {rep['ref']}**\n\n{rep['guide']}{notes}")

        if prefix == "vault:guide":
            from assistant_core.graph.guide import build_guide
            if not arg:
                return ExtResult("Usage: vault:guide <topic>", success=False, terminal=True)
            rep = build_guide(vault, router, arg, rag=rag,
                              include_private=bool((ctx.config or {}).get("graph_include_private", False)))
            if rep.get("error"):
                return ExtResult(rep["error"], success=False)
            _episode(ctx, "guide", arg[:80])
            src = f"\n\n*Sources: {', '.join(rep['sources'][:8])}*" if rep.get("sources") else ""
            return ExtResult(f"**Guide: {rep['entity']}**\n\n{rep['guide']}{src}")

        # ---- action commands (terminal confirmation) ----
        if prefix == "vault:ingest":
            from assistant_core.ingest.ingest import ingest_file
            if not arg:
                return ExtResult("Usage: vault:ingest <path to document>", success=False, terminal=True)
            rep = ingest_file(vault, arg, ctx.config, rag=rag, router=router)
            if rep.get("error"):
                return ExtResult(f"Ingest failed: {rep['error']}.", success=False, terminal=True)
            _episode(ctx, "ingest", f"{arg} → {rep.get('note_dir') or rep['note_path']}")
            if rep.get("format") == "html-set":
                return ExtResult(f"Imported HTML collection {rep['collection']} — {rep['files']} note(s) "
                                 f"→ {rep['note_dir']}/ with inter-file links rewritten to wikilinks.",
                                 terminal=True)
            return ExtResult(f"Ingested {rep['format']} ({rep['pages']} page(s), {rep['chars']} chars) "
                             f"→ {rep['note_path']} — now searchable.", terminal=True)

        if prefix == "vault:ocr":
            from assistant_core.media.ocr import OcrEngine, make_vision_fn
            if not arg:
                return ExtResult("Usage: vault:ocr <note>", success=False, terminal=True)
            engine = OcrEngine(vault, vision_fn=make_vision_fn(router, ctx.config))
            rep = engine.ocr_note(arg, private=private)
            if rep.get("error"):
                return ExtResult(f"OCR: {rep['error']}", success=False, terminal=True)
            _episode(ctx, "ocr", f"{arg} → {rep.get('sidecar')}")
            return ExtResult(f"OCR: {rep['ocred']}/{rep['images']} image(s) → {rep['sidecar']}.", terminal=True)

        if prefix == "vault:analyze":
            from assistant_core.media.ocr import analyze_image
            if not arg:
                return ExtResult("Usage: vault:analyze <image>", success=False, terminal=True)
            text, err = analyze_image(vault, arg, router, ctx.config, private=private)
            if err:
                return ExtResult(f"Image analysis failed: {err}.", success=False, terminal=True)
            _episode(ctx, "analyze", arg[:80])
            return ExtResult(f"**Image: {arg}**\n\n{text}", terminal=True)

        if prefix == "vault:graph":
            from assistant_core.graph.job import build_graph_for_note
            if not arg:
                return ExtResult("Usage: vault:graph <note>", success=False, terminal=True)
            rep = build_graph_for_note(vault, router, arg)
            if rep.get("error"):
                return ExtResult(f"Graph: {rep['error']}", success=False, terminal=True)
            _episode(ctx, "graph", f"{arg}: {rep.get('triples', 0)}")
            return ExtResult(f"Graph: {rep['triples']} relationship(s) from {arg}.", terminal=True)

        if prefix == "vault:graph-merge":
            from assistant_core.graph.store import merge_entities
            sep = "->" if "->" in arg else ("=>" if "=>" in arg else None)
            if not sep:
                return ExtResult("Usage: vault:graph-merge <canonical> -> <alias>", success=False, terminal=True)
            canon, alias = (p.strip() for p in arg.split(sep, 1))
            ok = merge_entities(vault, canon, alias)
            return ExtResult(f"Merged '{alias}' → '{canon}'." if ok else
                             "Could not merge (check both entities exist and differ).", success=ok, terminal=True)

        if prefix == "vault:transcribe":
            from assistant_core.media.audio import transcribe_to_sidecar
            if not arg:
                return ExtResult("Usage: vault:transcribe <audio>", success=False, terminal=True)
            rep = transcribe_to_sidecar(vault, arg, ctx.config, rag=rag)
            if rep.get("error"):
                return ExtResult(f"Transcription failed: {rep['error']}.", success=False, terminal=True)
            _episode(ctx, "transcribe", arg[:80])
            return ExtResult(f"Transcribed ({rep['chars']} chars) → {rep['sidecar']} — now searchable.", terminal=True)

        if prefix == "vault:cards":
            from assistant_core.study.cards import generate_cards, add_cards
            if not arg:
                return ExtResult("Usage: vault:cards <note>", success=False, terminal=True)
            res = ctx.registry.run("read_note", arg) if ctx.registry else None
            if not res or not getattr(res, "success", False):
                return ExtResult(f"Could not read {arg}.", success=False, terminal=True)
            cards = generate_cards(router, res.output)
            added = add_cards(vault, cards, (getattr(res, "metadata", None) or {}).get("path", arg))
            _episode(ctx, "cards", f"{arg}: {added}")
            return ExtResult(f"Added {added} review card(s) from {arg} (of {len(cards)} generated).", terminal=True)

        if prefix == "vault:review":
            from assistant_core.study.cards import due_cards
            due = due_cards(vault)
            if not due:
                return ExtResult("No cards due for review. 🎉", terminal=True)
            return ExtResult(f"{len(due)} card(s) due:\n\n" + "\n\n".join(
                f"**Q:** {c['q']}\n**A:** {c['a']}  _(from {c['source']})_" for c in due[:10]), terminal=True)

    except Exception as exc:
        logger.error(f"[vault_dispatch] {prefix} failed: {exc}")
        return ExtResult(f"{prefix} failed: {exc}", success=False, terminal=True)

    return None


def _episode(ctx, kind: str, detail: str) -> None:
    if getattr(ctx, "memory", None) and getattr(ctx, "ep_vault_fn", None):
        try:
            ctx.memory.append_episode(ctx.ep_vault_fn(kind, detail + " [agent]"))
        except Exception:
            pass


def _strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[end + 4:].lstrip("\n")
    return text

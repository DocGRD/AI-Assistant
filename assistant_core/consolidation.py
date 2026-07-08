"""
Dreaming & consolidation — Milestone 17 (Slice 1 engine + one-shot driver).

A nightly offline pass that turns *episodic* memory into *durable* facts WITHOUT
touching live memory. It:

  1. reads episode notes newer than a **watermark** (idempotent re-runs),
  2. asks an LLM — **forced private** routing (no-train providers only, no web handoff)
     with a conservative prompt — to extract a few high-confidence durable facts per day,
  3. **dedupes** candidates against existing `Learned-Facts` with the local embedder,
  4. writes a review note to `AI/Memory/proposed/consolidation-YYYY-MM-DD.md`.

Propose/commit: `Learned-Facts` is only changed when the user (or `--apply`) accepts.
Privacy is forced; cost is bounded (one short call per new day). Designed so the router
and embedder are injectable, so the whole flow is testable without network or models.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger("assistant")

EPISODES_DIR  = "AI/Memory/Episodes"
ARCHIVE_DIR   = "AI/Memory/Episodes/Archive"
FACTS_FILE    = "AI/Memory/Facts/Learned-Facts.md"
PROPOSED_DIR  = "AI/Memory/proposed"
STATE_FILE    = "AI/Memory/.consolidation-state.json"

_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.md$")
_DUP_THRESHOLD = 0.86   # cosine — above this a candidate is "already known"

EXTRACT_SYSTEM = (
    "You consolidate a day's assistant activity log into a SHORT list of durable, "
    "reusable facts about the user, their projects, and decisions. Be conservative: "
    "only include things clearly true and worth remembering long-term. Output 0-6 bullet "
    "points, each a single self-contained sentence starting with '- '. Do NOT include "
    "transient chatter, questions, tool mechanics, or anything you are unsure about. If "
    "nothing is worth keeping, output exactly 'NONE'."
)


# ── watermark state ────────────────────────────────────────────────────────

def _state_path(vault) -> Path:
    return Path(vault) / STATE_FILE


def read_watermark(vault) -> str:
    try:
        return json.loads(_state_path(vault).read_text(encoding="utf-8")).get("watermark", "")
    except Exception:
        return ""


def write_watermark(vault, date_str: str) -> None:
    try:
        p = _state_path(vault)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"watermark": date_str}), encoding="utf-8")
    except Exception as exc:
        logger.debug(f"[Consolidation] Could not persist watermark: {exc}")


def episode_files_since(vault, watermark: str, before: str | None = None) -> list[Path]:
    """Dated episode files (YYYY-MM-DD.md) with watermark < date < before.

    `before` (usually today) excludes the in-progress current day so it isn't
    half-consolidated — only complete days are processed, and the watermark only
    advances over them."""
    ep_dir = Path(vault) / EPISODES_DIR
    out = []
    for p in ep_dir.glob("*.md") if ep_dir.is_dir() else []:
        m = _DATE_RE.match(p.name)
        if m and m.group(1) > watermark and (before is None or m.group(1) < before):
            out.append(p)
    return sorted(out, key=lambda p: p.name)


# ── fact extraction + dedupe ───────────────────────────────────────────────

def parse_facts(reply: str) -> list[str]:
    """Pull '- ' bullet lines from an LLM reply; '' if it said NONE."""
    if reply.strip().upper().startswith("NONE"):
        return []
    facts = []
    for line in reply.splitlines():
        m = re.match(r"^\s*[-*]\s+(.+)$", line)
        if m:
            fact = m.group(1).strip().rstrip(".")
            if fact and fact.upper() != "NONE":
                facts.append(fact)
    return facts


def extract_candidate_facts(router, episode_text: str) -> list[str]:
    """One forced-private LLM call → candidate durable facts for a day."""
    from assistant_core.providers.base_provider import Message
    msgs = [Message(role="user", content=f"Activity log:\n\n{episode_text[:8000]}")]
    reply, _ = router.generate(
        messages=msgs, system_prompt=EXTRACT_SYSTEM,
        private=True, allow_webui_on_private=False,
    )
    return parse_facts(reply or "")


def existing_facts(vault) -> list[str]:
    """Fact text from Learned-Facts.md ('- [ts] fact' or '- fact' lines)."""
    try:
        text = (Path(vault) / FACTS_FILE).read_text(encoding="utf-8")
    except Exception:
        return []
    facts = []
    for line in text.splitlines():
        m = re.match(r"^\s*[-*]\s+(?:\[[^\]]*\]\s*)?(.+)$", line)
        if m and m.group(1).strip():
            facts.append(m.group(1).strip())
    return facts


def _cosine(a, b) -> float:
    import numpy as np
    a = np.asarray(a, dtype=float); b = np.asarray(b, dtype=float)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(a.dot(b) / (na * nb))


def dedupe_against_existing(candidates: list[str], existing: list[str],
                            embedder, threshold: float = _DUP_THRESHOLD):
    """Split candidates into (new, duplicates). Without an embedder or existing facts,
    only exact-text matches are treated as duplicates."""
    if not candidates:
        return [], []
    existing_lower = {e.lower() for e in existing}
    if embedder is None or not existing:
        new = [c for c in candidates if c.lower() not in existing_lower]
        dups = [c for c in candidates if c.lower() in existing_lower]
        return new, dups

    cand_vecs = embedder.embed(candidates)
    ex_vecs   = embedder.embed(existing)
    new, dups = [], []
    for c, cv in zip(candidates, cand_vecs):
        if c.lower() in existing_lower or max(_cosine(cv, ev) for ev in ex_vecs) >= threshold:
            dups.append(c)
        else:
            new.append(c)
    return new, dups


# ── proposal note ──────────────────────────────────────────────────────────

def _unsourced_quantity_facts(vault, facts: list[str]) -> list[str]:
    """M37 — facts that assert a checkable quantity the rest of the vault doesn't support.
    Conservative: only quantity-bearing facts are checked (preferences etc. are never flagged)."""
    from assistant_core.write_guard import _claims
    from assistant_core.provenance import find_sources
    out = []
    for f in facts:
        try:
            if _claims(f) and not find_sources(vault, f, limit=1).get("sourced"):
                out.append(f)
        except Exception:
            continue
    return out


def build_proposal(run_date: str, per_day: dict[str, list[str]],
                   new_facts: list[str], dups: list[str], vault=None) -> str:
    lines = [
        f"# Memory consolidation proposal — {run_date}",
        "",
        "*Proposed durable facts from recent episodes. Review and accept the ones worth "
        "keeping, then merge into Learned-Facts (or run `--consolidate --apply`). Live "
        "memory was NOT changed.*",
        "",
        "## Proposed new facts",
        "",
    ]
    if new_facts:
        lines += [f"- [ ] {f}" for f in new_facts]
        flagged = _unsourced_quantity_facts(vault, new_facts) if vault else []
        if flagged:
            lines += ["", "> [!warning] These assert quantities not found elsewhere in your "
                      "vault — verify before keeping:"]
            lines += [f"> - {f}" for f in flagged]
    else:
        lines.append("_(none — nothing new worth keeping)_")
    if dups:
        lines += ["", "## Skipped (already known / near-duplicate)", ""]
        lines += [f"- {d}" for d in dups]
    lines += ["", "## Per-day extraction", ""]
    for day in sorted(per_day):
        lines.append(f"### {day}")
        lines += ([f"- {f}" for f in per_day[day]] or ["- (nothing extracted)"])
        lines.append("")
    return "\n".join(lines)


# ── archival (Slice 2 — mechanical, additive, reversible) ──────────────────

def archive_old_episodes(vault, keep_days: int, today: str | None = None) -> dict:
    """Move raw daily episodes older than `keep_days` into `Episodes/Archive/` and log
    each in a monthly digest index (`Archive/digest-YYYY-MM.md`). Reversible (originals
    are moved, not deleted) and additive. The current day and anything already archived
    are left alone. Returns {"archived": [days], "digests": [paths]}."""
    today_dt = datetime.strptime(today or datetime.now().strftime("%Y-%m-%d"), "%Y-%m-%d")
    cutoff   = today_dt - timedelta(days=keep_days)
    ep_dir   = Path(vault) / EPISODES_DIR
    arc_dir  = Path(vault) / ARCHIVE_DIR
    report = {"archived": [], "digests": []}
    if not ep_dir.is_dir():
        return report

    for p in sorted(ep_dir.glob("*.md")):
        m = _DATE_RE.match(p.name)
        if not m:
            continue
        try:
            day_dt = datetime.strptime(m.group(1), "%Y-%m-%d")
        except ValueError:
            continue
        if day_dt >= cutoff:
            continue   # still recent (or today) — keep raw

        day = m.group(1)
        try:
            content  = p.read_text(encoding="utf-8")
            sessions = content.count("## Session")
            arc_dir.mkdir(parents=True, exist_ok=True)
            dest = arc_dir / p.name
            if dest.exists():                       # don't clobber a prior archive copy
                dest = arc_dir / f"{day}-{datetime.now().strftime('%H%M%S')}.md"
            p.replace(dest)

            digest = arc_dir / f"digest-{day[:7]}.md"
            if not digest.exists():
                digest.write_text(f"# Episode digest — {day[:7]}\n\n"
                                  "*Index of archived daily episodes (raw notes live beside this file).*\n\n",
                                  encoding="utf-8")
            with open(digest, "a", encoding="utf-8") as fh:
                fh.write(f"- [[{dest.stem}]] — {sessions or 1} session(s)\n")
            report["archived"].append(day)
            rel_digest = f"{ARCHIVE_DIR}/{digest.name}"
            if rel_digest not in report["digests"]:
                report["digests"].append(rel_digest)
            logger.info(f"[Consolidation] Archived episode {day} → {ARCHIVE_DIR}/")
        except Exception as exc:
            logger.warning(f"[Consolidation] Could not archive {day}: {exc}")
    return report


# ── proposal review (Slice 4 — plugin Memory-review panel) ─────────────────

_CHECKBOX_RE = re.compile(r"^\s*[-*]\s*\[[ xX]?\]\s*(.+)$")


def list_proposals(vault) -> list[dict]:
    """Pending consolidation proposals as {file, path, facts: [str]} (the '- [ ] fact'
    lines under 'Proposed new facts'). Used by the plugin's Memory-review panel."""
    pdir = Path(vault) / PROPOSED_DIR
    out = []
    for p in sorted(pdir.glob("consolidation-*.md")) if pdir.is_dir() else []:
        facts = []
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                m = _CHECKBOX_RE.match(line)
                if m and m.group(1).strip():
                    facts.append(m.group(1).strip())
        except Exception:
            continue
        if facts:
            out.append({"file": p.name, "path": f"{PROPOSED_DIR}/{p.name}", "facts": facts})
    return out


def _remaining_facts(target: Path) -> list[str]:
    facts = []
    try:
        for line in target.read_text(encoding="utf-8").splitlines():
            m = _CHECKBOX_RE.match(line)
            if m and m.group(1).strip():
                facts.append(m.group(1).strip())
    except Exception:
        pass
    return facts


def _drop_fact_line(target: Path, fact: str) -> None:
    """Remove the single checkbox line for `fact` from a proposal, deleting the file once
    no facts remain (so per-item resolution mirrors the organize pending store)."""
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    kept, removed = [], False
    for line in lines:
        m = _CHECKBOX_RE.match(line)
        if not removed and m and m.group(1).strip() == fact.strip():
            removed = True
            continue
        kept.append(line)
    if any(_CHECKBOX_RE.match(l) and _CHECKBOX_RE.match(l).group(1).strip() for l in kept):
        target.write_text("\n".join(kept) + "\n", encoding="utf-8")
    else:
        try:
            target.unlink()        # last fact resolved → remove the proposal note
        except Exception:
            pass


def apply_fact(vault, filename: str, fact: str) -> dict:
    """Accept ONE proposed fact: append it to Learned-Facts and drop just that line
    (resolving the proposal when it was the last one). Records positive feedback."""
    from assistant_core import feedback
    vault = Path(vault)
    target = vault / PROPOSED_DIR / Path(filename).name
    if not target.exists():
        return {"applied": 0, "resolved": True}
    run_date = datetime.now().strftime("%Y-%m-%d")
    facts_path = vault / FACTS_FILE
    try:
        facts_path.parent.mkdir(parents=True, exist_ok=True)
        with open(facts_path, "a", encoding="utf-8") as fh:
            fh.write(f"- [{run_date} consolidated] {fact}\n")
    except Exception as exc:
        logger.error(f"[Consolidation] apply_fact failed: {exc}")
        return {"applied": 0, "resolved": False}
    feedback.record("fact", fact, True)
    _drop_fact_line(target, fact)
    return {"applied": 1, "resolved": not target.exists()}


def reject_fact(vault, filename: str, fact: str) -> dict:
    """Dismiss ONE proposed fact: record negative feedback and drop just that line."""
    from assistant_core import feedback
    target = Path(vault) / PROPOSED_DIR / Path(filename).name
    feedback.record("fact", fact, False)
    if target.exists():
        _drop_fact_line(target, fact)
    return {"rejected": True, "resolved": not target.exists()}


def apply_proposal(vault, filename: str, accepted: list[str]) -> dict:
    """Append accepted facts to Learned-Facts and resolve the proposal (delete it).
    Path-jailed to the proposals dir. Returns {applied: int, resolved: bool}."""
    vault = Path(vault)
    name = Path(filename).name   # ignore any directory part — jail to proposals dir
    target = vault / PROPOSED_DIR / name
    run_date = datetime.now().strftime("%Y-%m-%d")
    applied = 0
    if accepted:
        facts_path = vault / FACTS_FILE
        try:
            facts_path.parent.mkdir(parents=True, exist_ok=True)
            with open(facts_path, "a", encoding="utf-8") as fh:
                for f in accepted:
                    fh.write(f"- [{run_date} consolidated] {f}\n")
                fh.flush()
            applied = len(accepted)
        except Exception as exc:
            logger.error(f"[Consolidation] apply_proposal failed: {exc}")
            return {"applied": 0, "resolved": False}
    resolved = False
    try:
        if target.exists():
            target.unlink()       # reviewed → remove the proposal note
            resolved = True
    except Exception as exc:
        logger.warning(f"[Consolidation] Could not remove proposal {name}: {exc}")
    logger.info(f"[Consolidation] Applied {applied} fact(s) from {name}; resolved={resolved}")
    return {"applied": applied, "resolved": resolved}


# ── engine ─────────────────────────────────────────────────────────────────

class ConsolidationEngine:
    def __init__(self, vault_path, router, embedder=None):
        self._vault    = Path(vault_path)
        self._router   = router
        self._embedder = embedder

    def run(self, apply: bool = False, archive_days: int | None = None) -> dict:
        """Returns a report dict: processed days, new facts, duplicates, proposal path,
        and (if `archive_days` set) archived days. Consolidation runs first, then the
        mechanical archival of episodes older than `archive_days`."""
        watermark = read_watermark(self._vault)
        today = datetime.now().strftime("%Y-%m-%d")
        files = episode_files_since(self._vault, watermark, before=today)
        report = {"days": [], "new_facts": [], "duplicates": [], "proposal": None,
                  "applied": False, "archived": []}
        if not files:
            logger.info("[Consolidation] No new episodes since watermark.")
            if archive_days is not None:
                report["archived"] = archive_old_episodes(self._vault, archive_days, today)["archived"]
            return report

        per_day: dict[str, list[str]] = {}
        all_candidates: list[str] = []
        for f in files:
            day = _DATE_RE.match(f.name).group(1)
            try:
                text = f.read_text(encoding="utf-8")
            except Exception:
                continue
            facts = extract_candidate_facts(self._router, text)
            per_day[day] = facts
            all_candidates.extend(facts)
            report["days"].append(day)

        # Dedupe across the whole batch + against existing facts.
        seen, batch = set(), []
        for c in all_candidates:
            if c.lower() not in seen:
                seen.add(c.lower()); batch.append(c)
        new_facts, dups = dedupe_against_existing(batch, existing_facts(self._vault), self._embedder)
        report["new_facts"], report["duplicates"] = new_facts, dups

        run_date = datetime.now().strftime("%Y-%m-%d")
        proposal = build_proposal(run_date, per_day, new_facts, dups, vault=self._vault)
        out = self._vault / PROPOSED_DIR / f"consolidation-{run_date}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(proposal, encoding="utf-8")
        report["proposal"] = f"{PROPOSED_DIR}/consolidation-{run_date}.md"
        logger.info(f"[Consolidation] {len(new_facts)} new fact(s) proposed → {report['proposal']}")

        # Advance the watermark to the latest processed day (idempotent re-runs).
        write_watermark(self._vault, max(report["days"]))

        if apply and new_facts:
            self._append_facts(new_facts, run_date)
            report["applied"] = True

        # Slice 2 — mechanical archival of episodes older than archive_days (runs last,
        # after their content has been consolidated above).
        if archive_days is not None:
            report["archived"] = archive_old_episodes(self._vault, archive_days, today)["archived"]
        return report

    def _append_facts(self, facts: list[str], run_date: str) -> None:
        facts_path = self._vault / FACTS_FILE
        try:
            facts_path.parent.mkdir(parents=True, exist_ok=True)
            with open(facts_path, "a", encoding="utf-8") as fh:
                for f in facts:
                    fh.write(f"- [{run_date} consolidated] {f}\n")
                fh.flush()
            logger.info(f"[Consolidation] Applied {len(facts)} fact(s) to {FACTS_FILE}")
        except Exception as exc:
            logger.error(f"[Consolidation] Could not apply facts: {exc}")

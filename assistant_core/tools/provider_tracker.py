"""
Tool: update_providers  (command: vault:update-providers [provider|apply])
Milestone 10 — self-updating provider registry, PROPOSE / COMMIT only.

This tool NEVER overwrites AI/System/Provider-Registry.md directly.

  vault:update-providers            → fetch the configured machine-readable source
  vault:update-providers <provider>   (plain HTTP, not an AI call), diff it against
                                      the live registry, and write the proposal to
                                      AI/System/Provider-Registry-proposed.md.
  vault:update-providers apply      → commit the approved proposal into
                                      AI/System/Provider-Registry.md.

If no source URL is configured (settings `provider_source_url`), or the source
cannot be parsed, the tool falls back to emitting a `vault:research` prompt for a
web-AI handoff — the pasted result can be integrated the same way.

The HTTP source may be either:
  - JSON: a list of row objects (or {"providers": [...]}), or
  - Markdown: the same table schema as Provider-Registry.md (parsed by RegistryLoader).
"""

import json
import logging
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path

from assistant_core.tools.base_tool import BaseTool, ToolResult
from assistant_core.providers.model_registry import ModelSpec
from assistant_core.providers.registry_loader import (
    RegistryLoader,
    NO_KNOWN_LIMIT,
    _parse_limit,
)

logger = logging.getLogger("assistant")

REGISTRY_REL = "AI/System/Provider-Registry.md"
PROPOSED_REL = "AI/System/Provider-Registry-proposed.md"

# Delimits the ready-to-publish registry inside the proposal note. `apply` copies
# exactly what is between these markers into Provider-Registry.md.
BEGIN_MARK = "<!-- BEGIN PROPOSED REGISTRY -->"
END_MARK   = "<!-- END PROPOSED REGISTRY -->"

# Identity of a row = (provider_key, model_id). These are the fields we diff.
_DIFF_FIELDS = [
    "base_url", "context_window", "tpm_limit", "rpm_limit", "rpd_limit",
    "tpd_limit", "trains_on_data", "status", "strengths", "notes",
]


def _limit_to_str(value: int) -> str:
    return "?" if value >= NO_KNOWN_LIMIT else str(value)


class ProviderTrackerTool(BaseTool):
    """Propose/commit updates to the provider registry from a machine-readable source."""

    def __init__(self, vault_path: str, config: dict | None = None):
        self._vault  = Path(vault_path)
        self._config = config or {}

    @property
    def name(self) -> str:
        return "update_providers"

    @property
    def description(self) -> str:
        return ("Propose provider-registry updates from a configured source "
                "(vault:update-providers [provider]); 'apply' commits the proposal.")

    # ------------------------------------------------------------------
    # Entry
    # ------------------------------------------------------------------

    def run(self, input_data: str) -> ToolResult:
        arg = (input_data or "").strip()
        if arg.lower() == "apply":
            return self._apply()
        return self._propose(provider_filter=arg.lower() or None)

    # ------------------------------------------------------------------
    # Propose
    # ------------------------------------------------------------------

    def _propose(self, provider_filter: str | None) -> ToolResult:
        source_url = (self._config.get("provider_source_url") or "").strip()
        if not source_url:
            return self._research_fallback("No 'provider_source_url' configured in settings.")

        try:
            raw = self._fetch(source_url)
        except Exception as exc:
            logger.warning(f"[update_providers] Fetch failed: {exc}")
            return self._research_fallback(f"Could not fetch source ({exc}).")

        try:
            source_specs = self._parse_source(raw)
        except Exception as exc:
            logger.warning(f"[update_providers] Parse failed: {exc}")
            return self._research_fallback(f"Could not parse source ({exc}).")

        if not source_specs:
            return self._research_fallback("Source contained no usable provider rows.")

        if provider_filter:
            source_specs = [s for s in source_specs if s.provider == provider_filter]
            if not source_specs:
                return ToolResult(success=False,
                                  output=f"Source has no rows for provider '{provider_filter}'.")

        current = self._load_current()
        diff_text = self._diff(current, source_specs, provider_filter)
        proposed_md = self._build_registry_md(source_specs)

        note = (
            f"# Provider Registry — Proposed Update\n\n"
            f"*Generated: {date.today().isoformat()} from `{source_url}`*\n\n"
            f"Review the changes below. To accept, run `vault:update-providers apply` "
            f"(this replaces `Provider-Registry.md` with the block at the bottom of this note). "
            f"To reject, delete this file. **`Provider-Registry.md` is untouched until you apply.**\n\n"
            f"## Diff vs current registry\n\n{diff_text}\n\n"
            f"## Proposed registry (applied verbatim on `apply`)\n\n"
            f"{BEGIN_MARK}\n{proposed_md}\n{END_MARK}\n"
        )

        proposed_path = self._vault / PROPOSED_REL
        try:
            proposed_path.parent.mkdir(parents=True, exist_ok=True)
            proposed_path.write_text(note, encoding="utf-8")
        except Exception as exc:
            return ToolResult(success=False, output=f"Could not write proposal: {exc}")

        logger.info(f"[update_providers] Proposal written to {PROPOSED_REL}")
        return ToolResult(
            success=True,
            output=(f"Proposal written to {PROPOSED_REL} (Provider-Registry.md untouched).\n\n"
                    f"{diff_text}\n\nRun `vault:update-providers apply` to commit."),
            metadata={"proposed_path": str(proposed_path), "rows": len(source_specs)},
        )

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _apply(self) -> ToolResult:
        proposed_path = self._vault / PROPOSED_REL
        if not proposed_path.exists():
            return ToolResult(success=False,
                              output=f"No proposal found at {PROPOSED_REL}. "
                                     f"Run `vault:update-providers` first.")
        try:
            note = proposed_path.read_text(encoding="utf-8")
        except Exception as exc:
            return ToolResult(success=False, output=f"Could not read proposal: {exc}")

        if BEGIN_MARK not in note or END_MARK not in note:
            return ToolResult(success=False,
                              output="Proposal is missing the registry block markers — not applying.")

        block = note.split(BEGIN_MARK, 1)[1].split(END_MARK, 1)[0].strip()
        if not block:
            return ToolResult(success=False, output="Proposed registry block is empty — not applying.")

        registry_path = self._vault / REGISTRY_REL
        try:
            registry_path.parent.mkdir(parents=True, exist_ok=True)
            registry_path.write_text(block + "\n", encoding="utf-8")
        except Exception as exc:
            return ToolResult(success=False, output=f"Could not write registry: {exc}")

        # Consume the proposal so it cannot be applied twice by accident.
        try:
            proposed_path.unlink()
        except Exception:
            pass

        logger.info("[update_providers] Applied proposal → Provider-Registry.md")
        return ToolResult(
            success=True,
            output=f"Applied proposal to {REGISTRY_REL}. Restart the assistant to route on the new registry.",
            metadata={"applied": True},
        )

    # ------------------------------------------------------------------
    # Source fetch + parse
    # ------------------------------------------------------------------

    def _fetch(self, url: str) -> str:
        """Plain HTTP GET (or file:// for local testing). Not an AI call."""
        req = urllib.request.Request(url, headers={"User-Agent": "AI-Assistant-ProviderTracker"})
        with urllib.request.urlopen(req, timeout=20) as resp:   # noqa: S310 (trusted, user-configured)
            return resp.read().decode("utf-8", errors="replace")

    def _parse_source(self, raw: str) -> list[ModelSpec]:
        stripped = raw.lstrip()
        if stripped.startswith("{") or stripped.startswith("["):
            return self._parse_json(stripped)
        # Otherwise assume the registry Markdown schema — reuse the loader.
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as fh:
            fh.write(raw)
            tmp = fh.name
        try:
            loader = RegistryLoader(Path(tmp))
            return loader.load()
        finally:
            try:
                Path(tmp).unlink()
            except Exception:
                pass

    def _parse_json(self, raw: str) -> list[ModelSpec]:
        data = json.loads(raw)
        rows = data.get("providers", []) if isinstance(data, dict) else data
        specs: list[ModelSpec] = []
        for row in rows:
            try:
                strengths = row.get("strengths", "")
                if isinstance(strengths, str):
                    strengths = [s.strip() for s in strengths.split(",") if s.strip()]
                specs.append(ModelSpec(
                    provider       = str(row["provider_key"]),
                    model_id       = str(row["model_id"]),
                    context_window = _parse_limit(str(row.get("context_window", "?"))),
                    tpm_limit      = _parse_limit(str(row.get("tpm", "?"))),
                    rpm_limit      = _parse_limit(str(row.get("rpm", "?"))),
                    rpd_limit      = _parse_limit(str(row.get("rpd", "?"))),
                    tpd_limit      = _parse_limit(str(row.get("tpd", "?"))),
                    strengths      = list(strengths),
                    weaknesses     = [],
                    notes          = str(row.get("notes", "")),
                    base_url       = str(row.get("base_url", "")),
                    status         = str(row.get("status", "active")),
                    trains_on_data = str(row.get("trains_on_data", "")),
                ))
            except (KeyError, ValueError) as exc:
                logger.warning(f"[update_providers] Skipping bad JSON row: {exc}")
        return specs

    def _load_current(self) -> list[ModelSpec]:
        return RegistryLoader(self._vault / REGISTRY_REL).load()

    # ------------------------------------------------------------------
    # Diff + render
    # ------------------------------------------------------------------

    def _diff(self, current: list[ModelSpec], proposed: list[ModelSpec],
              provider_filter: str | None) -> str:
        def key(s: ModelSpec) -> tuple[str, str]:
            return (s.provider, s.model_id)

        cur = {key(s): s for s in current
               if provider_filter is None or s.provider == provider_filter}
        new = {key(s): s for s in proposed}

        added   = [k for k in new if k not in cur]
        removed = [k for k in cur if k not in new]
        changed = []
        for k in new:
            if k in cur:
                deltas = [f for f in _DIFF_FIELDS if getattr(cur[k], f) != getattr(new[k], f)]
                if deltas:
                    changed.append((k, deltas))

        if not (added or removed or changed):
            return "_No changes — proposed registry matches the current one._"

        lines: list[str] = []
        for k in added:
            lines.append(f"- **ADD** `{k[0]}/{k[1]}` (status={new[k].status})")
        for k in removed:
            lines.append(f"- **REMOVE** `{k[0]}/{k[1]}`")
        for k, deltas in changed:
            detail = ", ".join(
                f"{f}: {getattr(cur[k], f)!r} -> {getattr(new[k], f)!r}" for f in deltas
            )
            lines.append(f"- **CHANGE** `{k[0]}/{k[1]}` — {detail}")
        return "\n".join(lines)

    def _build_registry_md(self, specs: list[ModelSpec]) -> str:
        """Render a complete Provider-Registry.md from a set of specs."""
        active    = [s for s in specs if s.status == "active"]
        candidate = [s for s in specs if s.status == "candidate"]

        header = (
            "# Provider Registry\n\n"
            f"*Last updated: {date.today().isoformat()}*\n"
            "*Update this file by running: `vault:update-providers`*\n\n"
            "This file is the single source of truth for every free-tier endpoint the router can use.\n"
            "Each **active** row becomes a live provider via the generic OpenAI-compatible adapter.\n"
        )
        out = [header, "## Active Providers\n", self._table(active)]
        if candidate:
            out += ["\n## Candidate Providers (registered, not routed until tested)\n",
                    self._table(candidate)]
        return "\n".join(out).rstrip() + "\n"

    def _table(self, specs: list[ModelSpec]) -> str:
        cols = ("provider_key", "base_url", "model_id", "context_window", "tpm",
                "rpm", "rpd", "tpd", "trains_on_data", "status", "strengths", "notes")
        rows = ["| " + " | ".join(cols) + " |",
                "|" + "|".join(["---"] * len(cols)) + "|"]
        for s in specs:
            rows.append("| " + " | ".join([
                s.provider,
                s.base_url,
                s.model_id,
                _limit_to_str(s.context_window),
                _limit_to_str(s.tpm_limit),
                _limit_to_str(s.rpm_limit),
                _limit_to_str(s.rpd_limit),
                _limit_to_str(s.tpd_limit),
                s.trains_on_data or "?",
                s.status,
                ", ".join(s.strengths),
                s.notes.replace("|", "\\|").replace("\n", " "),
            ]) + " |")
        return "\n".join(rows)

    # ------------------------------------------------------------------
    # Fallback — web-AI research handoff
    # ------------------------------------------------------------------

    def _research_fallback(self, reason: str) -> ToolResult:
        prompt = (
            "I maintain a routing registry of free-tier LLM API endpoints. Please return an "
            "up-to-date table (Markdown) of current free-tier providers with these columns: "
            "provider_key, base_url (OpenAI-compatible), model_id, context_window, tpm, rpm, rpd, "
            "tpd, trains_on_data (no|yes|logs|varies), status (active|candidate), strengths, notes. "
            "Use '?' for unknown numeric limits. Cover at least Groq, Google (Gemini, "
            "OpenAI-compatible endpoint), Cerebras, NVIDIA NIM, and OpenRouter. Be precise about "
            "current 2026 free-tier limits and whether each trains on submitted data."
        )
        return ToolResult(
            success=True,
            output=(f"{reason}\n\nFalling back to a web-AI research handoff. Paste the prompt below "
                    f"into a web AI, then save its Markdown table and re-run the update flow:\n\n"
                    f"------- COPY BELOW -------\n{prompt}\n------- COPY ABOVE -------"),
            metadata={"fallback": "research", "reason": reason},
        )

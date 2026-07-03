"""
Externalized task / planner state — Milestone 20, Slice 3.

The T5.01 analysis found that endpoint *switching* works well, but execution
*continuity* is weak: when the router hands a turn to a different provider mid-task,
the new model replans from the raw chat history and often restarts or re-introduces
work already done. The fix is to keep a small task ledger **outside** the model — the
goal plus a per-step checkpoint of what each tool actually did — and re-inject it into
the system prompt on every step. Because the ledger is rebuilt from external state
(not the model's memory), a provider switch resumes the *same* plan instead of
reinventing it.

Deliberately tiny: a goal line and the last few `✓/✗ step N (provider): tool detail`
checkpoints. It is appended to the system prompt, never sent as the user's words.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_MAX_SHOWN = 8     # only the most recent checkpoints — keep the injected block small


@dataclass
class Checkpoint:
    step:     int
    provider: str
    tool:     str
    ok:       bool
    detail:   str


@dataclass
class TaskLedger:
    goal:          str
    checkpoints:   list[Checkpoint] = field(default_factory=list)
    last_provider: str  = ""
    switched:      bool = False
    persist_path:  Path | None = None   # AI/System/Task-State.md (set by the loop)

    def note_provider(self, provider: str) -> None:
        """Record which provider ran this step; flag a mid-task switch for the prompt."""
        if self.last_provider and provider and provider != self.last_provider:
            self.switched = True
        if provider:
            self.last_provider = provider

    def record(self, step: int, provider: str, tool: str, ok: bool, detail: str) -> None:
        """Per-tool checkpoint — what ran, under which provider, and whether it worked."""
        first = (detail or "").splitlines()[0][:80] if detail else ""
        self.checkpoints.append(Checkpoint(step, provider, tool, ok, first))

    def render(self, current_step: int, max_steps: int) -> str:
        """Compact task-state block to append to the system prompt for this step."""
        goal = (self.goal or "").splitlines()[0][:200]
        lines = [
            "[TASK STATE — you are continuing ONE task that may span different AI "
            "models. Do NOT restart, re-introduce, or replan it from scratch; continue "
            "from what is already done below.]",
            f"Goal: {goal}",
        ]
        if self.checkpoints:
            lines.append("Done so far:")
            for c in self.checkpoints[-_MAX_SHOWN:]:
                icon = "✓" if c.ok else "✗"
                tail = f" {c.detail}" if c.detail else ""
                lines.append(f"  {icon} step {c.step} ({c.provider}): {c.tool}{tail}".rstrip())
        else:
            lines.append("Done so far: (nothing yet — this is the first step)")
        if self.switched:
            lines.append(
                f"NOTE: the model just changed to {self.last_provider} mid-task — "
                "pick up exactly where the previous step left off; do not start over."
            )
        lines.append(f"You are on step {current_step} of at most {max_steps}.")
        return "\n".join(lines)

    def persist(self, status: str = "in-progress",
                current_step: int = 0, max_steps: int = 0) -> None:
        """Write a human-readable task-state note to `persist_path` (best-effort).

        Lives at `AI/System/Task-State.md` — an RAG-excluded, non-`pending` path, so it
        never pollutes the index or triggers the watcher. Survives a crash: the user (or
        a fresh run) can read where the assistant left off and resume from the next step.
        Failures are swallowed — persistence must never break a turn."""
        if not self.persist_path:
            return
        try:
            lines = [
                "# Current Task State",
                "",
                "> Live scratchpad the assistant writes each step. If the service stopped "
                "mid-task, this is the goal and what was already done — resume from the next step.",
                "",
                f"- **Status:** {status}",
                f"- **Updated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"- **Provider (last step):** {self.last_provider or '—'}",
            ]
            if max_steps:
                lines.append(f"- **Step:** {current_step} of {max_steps}")
            lines += ["", "## Goal", "", (self.goal or "").strip() or "—", "", "## Steps so far", ""]
            if self.checkpoints:
                for c in self.checkpoints:
                    icon = "✓" if c.ok else "✗"
                    tail = f" — {c.detail}" if c.detail else ""
                    lines.append(f"- {icon} step {c.step} ({c.provider}): {c.tool}{tail}")
            else:
                lines.append("- (nothing yet)")
            lines.append("")
            self.persist_path.parent.mkdir(parents=True, exist_ok=True)
            self.persist_path.write_text("\n".join(lines), encoding="utf-8")
        except Exception:
            pass

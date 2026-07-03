"""
Find notes by glob — Milestone 16.6.

Enumerates notes matching a glob pattern (recursive `**` supported), with no 200-note
cap, so the agent can see a whole folder tree in one call instead of being told to
"look deeper" (T3.21). Read-only; safe to run autonomously.
"""

from pathlib import Path

from assistant_core.tools.base_tool import BaseTool, ToolResult

_PAGE = 300   # cap the printed list; report the true total


class FindNotesTool(BaseTool):
    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "find_notes"

    @property
    def description(self) -> str:
        return "Find notes by glob, e.g. find_notes 06 - Projects/**/*.md (recursive ** supported)."

    def run(self, input_data: str) -> ToolResult:
        pattern = (input_data or "").strip().replace("\\", "/").strip("\"'")
        if not pattern:
            return ToolResult(success=False,
                              output="Usage: vault:find <glob>  e.g.  06 - Projects/**/*.md")

        # A bare folder → list every note under it, recursively.
        if not any(c in pattern for c in "*?["):
            pattern = pattern.rstrip("/") + "/**/*.md"

        try:
            matches = sorted(
                str(p.relative_to(self._vault)).replace("\\", "/")
                for p in self._vault.glob(pattern)
                if p.is_file()
            )
        except Exception as exc:
            return ToolResult(success=False, output=f"Bad glob '{pattern}': {exc}")

        if not matches:
            return ToolResult(success=True, output=f"No notes match '{pattern}'.",
                              metadata={"count": 0})

        total = len(matches)
        shown = matches[:_PAGE]
        head = (f"Found {total} note(s) matching '{pattern}'"
                + (f" — showing the first {_PAGE} (narrow the glob to see more)" if total > _PAGE else "")
                + ":\n\n")
        return ToolResult(success=True, output=head + "\n".join(shown),
                          metadata={"count": total})

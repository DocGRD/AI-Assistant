"""
Tool: update_note — Milestone 7.5 patch 2

Changes:
  - _normalise_path() applied to the path before filesystem work.
    Consistent with create_note.py patch.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from assistant_core.tools.base_tool import BaseTool, ToolResult
from assistant_core.links import neutralize_dangling

logger = logging.getLogger("assistant")


def _normalise_path(rel_path: str) -> str:
    p = rel_path.replace("\\", "/")
    p = re.sub(r"/+", "/", p)
    return p.strip().strip("/")


class UpdateNoteTool(BaseTool):
    """Appends content to an existing vault note."""

    def __init__(self, vault_path: str, config: dict | None = None):
        self._vault = Path(vault_path)
        self._config = config or {}
        self._link_policy = self._config.get("link_validation", "strip")

    @property
    def name(self) -> str:
        return "update_note"

    @property
    def description(self) -> str:
        return "Append content to an existing vault note. Input: first line = path, remaining lines = content to append."

    def run(self, input_data: str) -> ToolResult:
        lines = input_data.strip().splitlines()
        if not lines:
            return ToolResult(success=False, output="No input provided.")

        rel_path = lines[0].strip()
        content  = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        if not rel_path:
            return ToolResult(success=False, output="Note path (first line) is empty.")
        if not content:
            return ToolResult(success=False, output="No content to append (lines after the path were empty).")

        rel_path = _normalise_path(rel_path)

        if not rel_path.endswith(".md"):
            rel_path += ".md"

        target = self._vault / rel_path

        if not target.exists():
            return ToolResult(
                success = False,
                output  = (
                    f"Note not found: {rel_path}\n"
                    "Use vault:create to create a new note."
                )
            )

        # M30 — strip fabricated [[links]] to notes that don't exist before appending.
        content, removed_links = neutralize_dangling(content, self._vault, self._link_policy)

        # M37 — trust on write: flag/source factual claims the vault can't support.
        from assistant_core.write_guard import guard_content
        private = bool(re.search(r"^private:\s*true", content, re.MULTILINE | re.IGNORECASE))
        content, guard_status = guard_content(self._vault, content, self._config, private=private)

        timestamp    = datetime.now().strftime("%Y-%m-%d %H:%M")
        append_block = f"\n\n---\n*Appended by Loremaster — {timestamp}*\n\n{content}\n"
        if removed_links:
            append_block += "\n*Removed unresolved links: " + ", ".join(removed_links) + "*\n"
            logger.info(f"[update_note] Neutralized {len(removed_links)} dangling link(s): {removed_links}")

        try:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(append_block)
            logger.info(f"[update_note] Appended {len(append_block)} chars to: {rel_path}")
            note = f" ({len(removed_links)} unresolved link(s) removed)" if removed_links else ""
            if guard_status == "flagged":
                note += " ⚠ unsourced claims flagged"
            return ToolResult(
                success  = True,
                output   = f"✓ Appended to: {rel_path}{note}",
                metadata = {"path": rel_path, "appended_chars": len(append_block),
                            "removed_links": removed_links, "guard": guard_status},
            )
        except Exception as exc:
            logger.error(f"[update_note] Failed: {exc}")
            return ToolResult(success=False, output=f"Could not update note: {exc}")

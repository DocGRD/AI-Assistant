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

logger = logging.getLogger("assistant")


def _normalise_path(rel_path: str) -> str:
    p = rel_path.replace("\\", "/")
    p = re.sub(r"/+", "/", p)
    return p.strip().strip("/")


class UpdateNoteTool(BaseTool):
    """Appends content to an existing vault note."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

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

        timestamp    = datetime.now().strftime("%Y-%m-%d %H:%M")
        append_block = f"\n\n---\n*Appended by AI Assistant — {timestamp}*\n\n{content}\n"

        try:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(append_block)
            logger.info(f"[update_note] Appended {len(append_block)} chars to: {rel_path}")
            return ToolResult(
                success  = True,
                output   = f"✓ Appended to: {rel_path}",
                metadata = {"path": rel_path, "appended_chars": len(append_block)},
            )
        except Exception as exc:
            logger.error(f"[update_note] Failed: {exc}")
            return ToolResult(success=False, output=f"Could not update note: {exc}")

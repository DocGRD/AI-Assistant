"""
Tool: update_note
Appends a new section to an existing Markdown note in the vault.

Input format:
    Line 1: relative path of the note to update (e.g. "AI/Memory/Projects/AI-Assistant.md")
    Line 2+: content to append

The tool always appends — it never overwrites existing content.
Each append is timestamped so you can see when sections were added.

Example input:
    AI/Memory/Projects/AI-Assistant.md
    ## Milestone 4 Decision
    Chose to use token estimation (1 token ≈ 4 chars) rather than a tokenizer library.
"""

import logging
from datetime import datetime
from pathlib import Path

from tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")


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

        if not rel_path.endswith(".md"):
            rel_path += ".md"

        target = self._vault / rel_path

        if not target.exists():
            return ToolResult(
                success=False,
                output=(
                    f"Note not found: {rel_path}\n"
                    "Use vault:create to create a new note."
                )
            )

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        append_block = f"\n\n---\n*Appended by AI Assistant — {timestamp}*\n\n{content}\n"

        try:
            with open(target, "a", encoding="utf-8") as fh:
                fh.write(append_block)
            logger.info(f"[update_note] Appended {len(append_block)} chars to: {rel_path}")
            return ToolResult(
                success=True,
                output=f"✓ Appended to: {rel_path}",
                metadata={"path": rel_path, "appended_chars": len(append_block)},
            )
        except Exception as exc:
            logger.error(f"[update_note] Failed: {exc}")
            return ToolResult(success=False, output=f"Could not update note: {exc}")

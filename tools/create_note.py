"""
Tool: create_note
Creates a new Markdown note in the vault.

Input format (two lines):
    Line 1: relative path for the new note (e.g. "AI/Research/topic.md")
    Line 2+: content of the note

Example input:
    AI/Research/hydroponic-barley.md
    # Hydroponic Barley Research
    
    Notes from research session 2026-06-06...

The tool will:
    - Create any missing parent folders
    - Refuse to overwrite an existing note (use update_note for that)
    - Return success/failure with the final path
"""

import logging
from datetime import datetime
from pathlib import Path

from tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")


class CreateNoteTool(BaseTool):
    """Creates a new Markdown note in the vault."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "create_note"

    @property
    def description(self) -> str:
        return "Create a new note in the vault. Input: first line = path, remaining lines = content."

    def run(self, input_data: str) -> ToolResult:
        lines = input_data.strip().splitlines()
        if not lines:
            return ToolResult(success=False, output="No input provided. First line must be the note path.")

        rel_path = lines[0].strip()
        content  = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""

        if not rel_path:
            return ToolResult(success=False, output="Note path (first line) is empty.")

        # Ensure .md extension
        if not rel_path.endswith(".md"):
            rel_path += ".md"

        target = self._vault / rel_path

        if target.exists():
            return ToolResult(
                success=False,
                output=(
                    f"Note already exists: {rel_path}\n"
                    "Use vault:update to append to it, or choose a different path."
                )
            )

        # Create parent folders if needed
        target.parent.mkdir(parents=True, exist_ok=True)

        # Add a creation timestamp comment if content doesn't already have one
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        if content and not content.startswith("#"):
            header = f"# {Path(rel_path).stem}\n\n"
            content = header + content

        final_content = content + f"\n\n---\n*Created by AI Assistant — {timestamp}*\n"

        try:
            target.write_text(final_content, encoding="utf-8")
            logger.info(f"[create_note] Created: {rel_path} ({len(final_content)} chars)")
            return ToolResult(
                success=True,
                output=f"✓ Note created: {rel_path}",
                metadata={"path": rel_path, "size_chars": len(final_content)},
            )
        except Exception as exc:
            logger.error(f"[create_note] Failed: {exc}")
            return ToolResult(success=False, output=f"Could not create note: {exc}")

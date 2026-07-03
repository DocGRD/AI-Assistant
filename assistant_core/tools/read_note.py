"""
Tool: read_note
Reads a single Markdown file from the Obsidian vault.

Input:  A file path relative to the vault root, OR just the note name.
        Examples:
            "Projects/Dairy-System/feed-plan.md"
            "feed-plan"          <- will search for the file
            "feed-plan.md"       <- will search for the file

Output: The full text content of the note, plus frontmatter if present.
"""

import logging
from pathlib import Path

from assistant_core.tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")


class ReadNoteTool(BaseTool):
    """Reads a single note from the vault."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "read_note"

    @property
    def description(self) -> str:
        return "Read the full text of a specific note in the Obsidian vault."

    def run(self, input_data: str) -> ToolResult:
        """
        input_data: relative path OR note name (with or without .md)
        """
        target = input_data.strip()
        if not target:
            return ToolResult(success=False, output="No file path or note name provided.")

        # Try as a direct relative path first
        candidate = self._vault / target
        if not candidate.suffix:
            candidate = candidate.with_suffix(".md")

        if candidate.exists():
            return self._read(candidate)

        # Fall back to searching the entire vault by filename
        note_name = Path(target).stem.lower()
        matches = [
            p for p in self._vault.rglob("*.md")
            if p.stem.lower() == note_name
        ]

        if len(matches) == 1:
            return self._read(matches[0])

        if len(matches) > 1:
            paths = "\n".join(str(m.relative_to(self._vault)) for m in matches)
            return ToolResult(
                success=False,
                output=f"Multiple notes named '{note_name}' found. Please use the full path:\n{paths}"
            )

        return ToolResult(
            success=False,
            output=f"Note not found: '{target}'\nTip: use 'search_vault' to locate it."
        )

    def _read(self, path: Path) -> ToolResult:
        try:
            content = path.read_text(encoding="utf-8")
            rel_path = path.relative_to(self._vault)
            logger.info(f"[read_note] Read {rel_path} ({len(content)} chars)")
            return ToolResult(
                success=True,
                output=content,
                metadata={
                    "path": str(rel_path),
                    "size_chars": len(content),
                    "full_path": str(path),
                }
            )
        except Exception as exc:
            logger.error(f"[read_note] Failed to read {path}: {exc}")
            return ToolResult(success=False, output=f"Could not read file: {exc}")

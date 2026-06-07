"""
Tool: summarise_research
Summarises a research note and appends conclusions to project memory.

Input: Relative path to a research note (e.g. "AI/Research/2026-06-06-hydroponic-barley.md")

The tool will:
    - Read the research note from the vault
    - Send it to the AI provider for summarisation
    - Extract bullet-point conclusions
    - Append summary to relevant project memory note
    - Return confirmation
"""

import logging
import re
from pathlib import Path

from tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")


class SummariseResearchTool(BaseTool):
    """Summarises research notes and updates project memory."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)
        self._research_dir = self._vault / "AI" / "Research"
        self._projects_dir = self._vault / "AI" / "Memory" / "Projects"
        self._projects_dir.mkdir(parents=True, exist_ok=True)

    @property
    def name(self) -> str:
        return "summarise_research"

    @property
    def description(self) -> str:
        return "Summarise a research note and append findings to project memory."

    def run(self, input_data: str) -> ToolResult:
        note_path = input_data.strip()
        if not note_path:
            return ToolResult(
                success=False,
                output="No path provided. Usage: vault:summarise <path to research note>"
            )

        # Resolve the note path
        if note_path.startswith("AI/Research/"):
            full_path = self._vault / note_path
        else:
            full_path = self._vault / "AI" / "Research" / note_path

        if not full_path.exists():
            return ToolResult(
                success=False,
                output=f"Research note not found: {note_path}"
            )

        try:
            content = full_path.read_text(encoding="utf-8")
        except Exception as exc:
            return ToolResult(success=False, output=f"Could not read note: {exc}")

        # Extract filename for metadata
        filename = full_path.name
        
        logger.info(f"[summarise_research] Processing: {filename}")
        return ToolResult(
            success=True,
            output=f"""✓ Research note loaded: {filename}

**Note:** Summarise_research requires provider interaction to generate conclusions.
This tool is called with the note content. The assistant will send it to the AI provider
for summarisation and append the results to project memory.

**Research note summary:**
{self._extract_preview(content)}

*Ready for assistant to summarise and append to project memory.*""",
            metadata={
                "path": note_path,
                "filename": filename,
                "content_length": len(content),
                "content_preview": self._extract_preview(content),
            },
        )

    def _extract_preview(self, content: str) -> str:
        """Extract a brief preview of the research content."""
        lines = content.strip().splitlines()
        
        # Skip title and metadata lines, get first few content lines
        preview_lines = []
        skip_count = 0
        for i, line in enumerate(lines):
            if line.startswith("#") or line.startswith("**") or line.startswith("---"):
                skip_count += 1
                continue
            if line.strip() and len(preview_lines) < 5:
                preview_lines.append(line.strip())
        
        preview = "\n".join(preview_lines)
        if len(preview) > 300:
            preview = preview[:300] + "..."
        
        return preview

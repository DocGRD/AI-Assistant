"""
Tool: summarise_research
Loads a research note into context and asks the assistant to summarise it.

Input: Relative path to a research note (e.g. "AI/Research/2026-06-06-hydroponic-barley.md")

The tool will:
    - Read the research note from the vault
    - Inject it into the AI context window
    - Ask the assistant to create a bullet-point summary
    - Return formatted content + summary request for the assistant to respond to
"""

import logging
from pathlib import Path

from tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")


class SummariseResearchTool(BaseTool):
    """Loads research notes into context and prompts assistant to summarise."""

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
        return "Load a research note into context and ask the assistant to summarise it."

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

        filename = full_path.name
        
        logger.info(f"[summarise_research] Loaded: {filename}")
        
        # Format the content with a clear request for the assistant to summarise
        formatted_output = f"""## Research Note: {filename}

{content}

---

**Summary Request:**
Please provide a concise bullet-point summary of this research, focusing on:
- **Key Facts:** The main findings or conclusions
- **Practical Applications:** How this knowledge can be used
- **Project Implications:** What this means for the current project

After you provide the summary, I can save it to the project memory using:
`vault:update AI/Memory/Projects/<project-name>.md`"""

        return ToolResult(
            success=True,
            output=formatted_output,
            metadata={
                "path": note_path,
                "filename": filename,
                "content_length": len(content),
            },
        )


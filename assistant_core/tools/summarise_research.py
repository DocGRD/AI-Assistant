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

from assistant_core.tools.base_tool import BaseTool, ToolResult

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

    def _resolve(self, note_path: str) -> Path | None:
        """Find the note the way read_note does: .md-append + direct path + AI/Research
        + vault-wide stem search. Returns the resolved Path or None."""
        target = note_path.replace("\\", "/").strip()

        candidate = self._vault / target
        if not candidate.suffix:
            candidate = candidate.with_suffix(".md")
        if candidate.exists():
            return candidate

        alt = self._research_dir / Path(target).name
        if not alt.suffix:
            alt = alt.with_suffix(".md")
        if alt.exists():
            return alt

        stem = Path(target).stem.lower()
        matches = [p for p in self._vault.rglob("*.md") if p.stem.lower() == stem]
        return matches[0] if len(matches) == 1 else None

    def run(self, input_data: str) -> ToolResult:
        note_path = input_data.strip()
        if not note_path:
            return ToolResult(
                success=False,
                output="No path provided. Usage: vault:summarise <path to research note>"
            )

        # Resolve robustly — mirror read_note: append .md if missing, try the given
        # path, then AI/Research/<name>, then a vault-wide search by stem. (T5.10: a
        # path without the .md extension used to fail here while read_note found it.)
        full_path = self._resolve(note_path)
        if full_path is None:
            return ToolResult(
                success=False,
                output=(f"Research note not found: {note_path}\n"
                        "Tip: pass the path with or without .md, or use vault:search to locate it.")
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
                "path": str(full_path.relative_to(self._vault)).replace("\\", "/"),
                "filename": filename,
                "content_length": len(content),
            },
        )


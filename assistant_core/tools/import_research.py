"""
Tool: import_research
Imports research from external AI services into vault research notes.

Input format:
    Pasted text from external AI (ChatGPT, Gemini, Grok, Perplexity, etc.)

The tool will:
    - Parse the pasted content
    - Extract key facts and structure
    - Write to AI/Research/YYYY-MM-DD-<slug>.md
    - Return the path of the created research note

M20 (T5.01 follow-up): an optional `title_fn` (one non-agentic LLM call, see
`research_roundtrip.generate_note_title`) gives the note a short 1-4 word name instead
of a slugified first sentence (e.g. "rocket-mass-heater" instead of
"a-rocket-mass-heater-is-a-wood-burning"). When absent or it fails, the original
first-line heuristic is used — fully backward compatible.
"""

import logging
import re
from datetime import datetime
from pathlib import Path

from assistant_core.tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")


class ImportResearchTool(BaseTool):
    """Imports research from external AI into vault research notes."""

    def __init__(self, vault_path: str, title_fn=None):
        self._vault = Path(vault_path)
        self._research_dir = self._vault / "AI" / "Research"
        self._research_dir.mkdir(parents=True, exist_ok=True)
        # Optional (content: str) -> str | None — one non-agentic LLM call for a short
        # title. Injected by ToolRegistry when a router is available; None elsewhere
        # (tests, no-router setups), which keeps the old heuristic slug behaviour.
        self._title_fn = title_fn

    @property
    def name(self) -> str:
        return "import_research"

    @property
    def description(self) -> str:
        return "Import research from external AI. Paste the AI response to save it."

    def run(self, input_data: str) -> ToolResult:
        content = input_data.strip()
        if not content:
            return ToolResult(
                success=False,
                output="No content provided. Paste the research text from external AI."
            )

        # Prefer a short LLM-generated title (1-4 words) for both the filename and the
        # heading; fall back to the original first-line heuristic if unavailable/empty.
        title = self._safe_title(content)
        slug  = self._slugify(title) if title else self._generate_slug(content)
        if not slug:
            slug = self._generate_slug(content)

        date_str = datetime.now().strftime("%Y-%m-%d")
        filename = f"{date_str}-{slug}.md"
        filepath = self._research_dir / filename

        # Ensure filename is unique
        counter = 1
        while filepath.exists():
            filename = f"{date_str}-{slug}-{counter}.md"
            filepath = self._research_dir / filename
            counter += 1

        # Format the content
        formatted = self._format_research(content, title_override=title)

        try:
            filepath.write_text(formatted, encoding="utf-8")
            relative_path = f"AI/Research/{filename}"
            logger.info(f"[import_research] Created: {relative_path}")
            return ToolResult(
                success=True,
                output=f"✓ Research imported: {relative_path}",
                metadata={"path": relative_path, "slug": slug, "title": title},
            )
        except Exception as exc:
            logger.error(f"[import_research] Failed: {exc}")
            return ToolResult(success=False, output=f"Could not save research: {exc}")

    def _safe_title(self, content: str) -> str | None:
        if not self._title_fn:
            return None
        try:
            return self._title_fn(content)
        except Exception as exc:
            logger.debug(f"[import_research] title_fn failed ({exc}) — using heuristic slug")
            return None

    @staticmethod
    def _slugify(text: str) -> str:
        slug = text.lower()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"\s+", "-", slug).strip("-")
        return slug[:40]

    def _generate_slug(self, content: str) -> str:
        """Generate a slug from the first meaningful line of content."""
        lines = content.strip().splitlines()
        
        # Find first non-empty line that looks like a heading
        first_line = ""
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                first_line = line
                break
        
        if not first_line:
            first_line = "research"

        # Remove markdown formatting and special chars
        slug = first_line.lower()
        slug = re.sub(r"[^\w\s-]", "", slug)  # remove special chars
        slug = re.sub(r"\s+", "-", slug)      # replace spaces with dashes
        slug = slug[:40]                       # limit length

        return slug or "research"

    def _format_research(self, content: str, title_override: str | None = None) -> str:
        """Format pasted content into a proper research note."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")

        if title_override:
            title = title_override
        else:
            # Extract or create a title from first line
            lines = content.strip().splitlines()
            title_line = None
            for line in lines:
                if line.strip():
                    title_line = line.strip()
                    break

            if not title_line:
                title_line = "Research Import"

            # Remove markdown formatting from title if present
            if title_line.startswith("#"):
                title = title_line.lstrip("#").strip()
            else:
                title = title_line

        # Build the formatted note
        formatted = f"""# {title}

**Source:** Imported from external AI research  
**Date:** {timestamp}

---

## Research Content

{content.strip()}

---

*Imported by AI Assistant — Milestone 5*
"""

        return formatted

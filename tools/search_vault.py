"""
Tool: search_vault
Searches all Markdown files in the vault for a query string.

Input:  A search query (plain text, case-insensitive).
        Examples:
            "hydroponic barley"
            "LangGraph state machine"
            "dairy feed"

Output: A ranked list of matching notes with the surrounding context
        (the line containing the match plus one line above and below).
        Results are sorted by number of matches (most matches first).
"""

import logging
import re
from pathlib import Path

from tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")

# Files and folders to skip during search
EXCLUDED_DIRS = {".obsidian", ".git", ".trash", ".venv"}
MAX_RESULTS = 20          # maximum number of matching files to return
MAX_SNIPPETS_PER_FILE = 3 # how many match snippets to show per file
CONTEXT_LINES = 1         # lines of context above and below each match


class SearchVaultTool(BaseTool):
    """Full-text search across all Markdown notes in the vault."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "search_vault"

    @property
    def description(self) -> str:
        return "Search all notes in the Obsidian vault for a text query. Returns matching notes with context snippets."

    def run(self, input_data: str) -> ToolResult:
        query = input_data.strip()
        if not query:
            return ToolResult(success=False, output="No search query provided.")

        if not self._vault.exists():
            return ToolResult(success=False, output=f"Vault not found at: {self._vault}")

        pattern = re.compile(re.escape(query), re.IGNORECASE)
        results: list[dict] = []

        for md_file in self._vault.rglob("*.md"):
            # Skip excluded directories
            if any(excluded in md_file.parts for excluded in EXCLUDED_DIRS):
                continue

            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue

            lines = content.splitlines()
            match_lines = [
                i for i, line in enumerate(lines)
                if pattern.search(line)
            ]

            if not match_lines:
                continue

            # Build context snippets
            snippets = []
            for line_idx in match_lines[:MAX_SNIPPETS_PER_FILE]:
                start = max(0, line_idx - CONTEXT_LINES)
                end   = min(len(lines), line_idx + CONTEXT_LINES + 1)
                snippet_lines = lines[start:end]
                # Highlight the matching line with >>
                relative_offset = line_idx - start
                snippet_lines[relative_offset] = ">> " + snippet_lines[relative_offset]
                snippets.append("\n".join(snippet_lines))

            results.append({
                "path":       str(md_file.relative_to(self._vault)),
                "match_count": len(match_lines),
                "snippets":   snippets,
            })

        if not results:
            return ToolResult(
                success=True,
                output=f"No notes found containing '{query}'."
            )

        # Sort by match count descending
        results.sort(key=lambda r: r["match_count"], reverse=True)
        top_results = results[:MAX_RESULTS]

        logger.info(f"[search_vault] '{query}' — {len(results)} files matched, showing {len(top_results)}")

        # Format output
        lines_out = [
            f"Search: '{query}'",
            f"Found {len(results)} note(s) — showing top {len(top_results)}:\n",
        ]

        for r in top_results:
            lines_out.append(f"### {r['path']}  ({r['match_count']} match(es))")
            for snippet in r["snippets"]:
                lines_out.append("```")
                lines_out.append(snippet)
                lines_out.append("```")
            lines_out.append("")

        return ToolResult(
            success=True,
            output="\n".join(lines_out),
            metadata={
                "query":         query,
                "total_matches": len(results),
                "shown":         len(top_results),
                "paths":         [r["path"] for r in top_results],
            }
        )

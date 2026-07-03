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

from assistant_core.tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")

# Files and folders to skip during search
EXCLUDED_DIRS = {".obsidian", ".git", ".trash", ".venv"}
# Path prefixes to skip — logs, not knowledge. Episode logs record every command
# (including your searches), so searching them just echoes your own query back (T5.14).
EXCLUDED_PREFIXES = ("AI/Memory/Episodes", "AI/Chat")
MAX_RESULTS = 20          # maximum number of matching files to return
MAX_SNIPPETS_PER_FILE = 3 # how many match snippets to show per file
CONTEXT_LINES = 1         # lines of context above and below each match
_WORD_RE = re.compile(r"\w+")


class SearchVaultTool(BaseTool):
    """Full-text search across all Markdown notes in the vault."""

    def __init__(self, vault_path: str, config: dict | None = None):
        self._vault = Path(vault_path)
        cfg = config or {}
        # Plugin-configurable folder scope. `search_include_folders` (whitelist) wins if
        # set; otherwise `search_exclude_folders` adds to the built-in log exclusions.
        self._include = [p.strip().strip("/").replace("\\", "/")
                         for p in (cfg.get("search_include_folders") or []) if p.strip()]
        self._exclude = list(EXCLUDED_PREFIXES) + [
            p.strip().strip("/").replace("\\", "/")
            for p in (cfg.get("search_exclude_folders") or []) if p.strip()]

    @property
    def name(self) -> str:
        return "search_vault"

    @property
    def description(self) -> str:
        return "Search all notes in the Obsidian vault for a text query. Returns matching notes with context snippets."

    def _skip(self, md_file: Path) -> bool:
        if any(excluded in md_file.parts for excluded in EXCLUDED_DIRS):
            return True
        rel = str(md_file.relative_to(self._vault)).replace("\\", "/")
        if self._include:                       # whitelist mode
            return not any(rel.startswith(p) for p in self._include)
        return any(rel.startswith(p) for p in self._exclude)

    def _scan(self, line_pred, note_pred) -> list[dict]:
        """Collect matching files. `note_pred(content_lower)` gates a whole note (used
        for all-words matching); `line_pred(line_lower)` marks the snippet lines."""
        results: list[dict] = []
        for md_file in self._vault.rglob("*.md"):
            if self._skip(md_file):
                continue
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception:
                continue
            if note_pred is not None and not note_pred(content.lower()):
                continue
            lines = content.splitlines()
            match_lines = [i for i, line in enumerate(lines) if line_pred(line.lower())]
            if not match_lines:
                continue
            snippets = []
            for line_idx in match_lines[:MAX_SNIPPETS_PER_FILE]:
                start = max(0, line_idx - CONTEXT_LINES)
                end   = min(len(lines), line_idx + CONTEXT_LINES + 1)
                snippet_lines = lines[start:end]
                snippet_lines[line_idx - start] = ">> " + snippet_lines[line_idx - start]
                snippets.append("\n".join(snippet_lines))
            results.append({"path": str(md_file.relative_to(self._vault)).replace("\\", "/"),
                            "match_count": len(match_lines), "snippets": snippets})
        results.sort(key=lambda r: r["match_count"], reverse=True)
        return results

    def run(self, input_data: str) -> ToolResult:
        query = input_data.strip()
        if not query:
            return ToolResult(success=False, output="No search query provided.")

        if not self._vault.exists():
            return ToolResult(success=False, output=f"Vault not found at: {self._vault}")

        q_lower = query.lower()
        words = [w for w in _WORD_RE.findall(q_lower) if len(w) >= 2]

        # Pass 1 — exact phrase (contiguous substring in a line).
        results = self._scan(lambda ln: q_lower in ln, note_pred=None)
        mode = "phrase"

        # Pass 2 — fall back to ALL-WORDS (order-independent) when the exact phrase
        # isn't found and the query has 2+ words. A note must contain every word
        # somewhere; snippet lines contain any word. (T5.14: "down to catch prey"
        # split across formatting, or a query with extra/reordered words, now matches.)
        if not results and len(words) >= 2:
            results = self._scan(lambda ln: any(w in ln for w in words),
                                 note_pred=lambda c: all(w in c for w in words))
            mode = "all-words"

        if not results:
            hint = ("" if len(words) < 2 else
                    " (tried the exact phrase and all words individually)")
            return ToolResult(success=True,
                              output=f"No notes found containing '{query}'{hint}.")

        top_results = results[:MAX_RESULTS]
        logger.info(f"[search_vault] '{query}' ({mode}) — {len(results)} files matched, "
                    f"showing {len(top_results)}")

        header = f"Search: '{query}'"
        if mode == "all-words":
            header += "  (no exact phrase — showing notes containing all the words)"
        lines_out = [
            header,
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

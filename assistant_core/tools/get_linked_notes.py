"""
Tool: get_linked_notes
Reads a note AND all notes it links to (via [[wikilinks]]).

This gives the assistant a richer picture of a topic without requiring
the user to manually specify every related note.

Input:  A note name or relative vault path (same as read_note).

Output: The content of the target note followed by each linked note,
        clearly labelled so the AI knows the provenance of each piece.
"""

import logging
import re
from pathlib import Path

from assistant_core.tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")

# Matches [[Link]] and [[Link|Alias]] style wikilinks
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:[|#][^\]]*)?\]\]")
MAX_LINKED_NOTES = 10   # cap to avoid flooding the context window


class GetLinkedNotesTool(BaseTool):
    """Reads a note and all notes it directly links to."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "get_linked_notes"

    @property
    def description(self) -> str:
        return "Read a note and all notes it links to via [[wikilinks]], providing rich context on a topic."

    def run(self, input_data: str) -> ToolResult:
        target = input_data.strip()
        if not target:
            return ToolResult(success=False, output="No note name or path provided.")

        # Resolve the root note
        root_path = self._resolve(target)
        if root_path is None:
            return ToolResult(
                success=False,
                output=f"Note not found: '{target}'. Use 'search_vault' to locate it."
            )

        root_content = self._read(root_path)
        sections: list[str] = [
            f"# {root_path.relative_to(self._vault)}\n\n{root_content}"
        ]

        # Extract wikilinks from the root note
        links = WIKILINK_RE.findall(root_content)
        unique_links = list(dict.fromkeys(links))  # deduplicate, preserve order

        loaded = 0
        missing = []

        for link in unique_links:
            if loaded >= MAX_LINKED_NOTES:
                sections.append(
                    f"\n---\n_Note: {len(unique_links) - loaded} more linked notes not loaded (limit reached)._"
                )
                break

            linked_path = self._resolve(link)
            if linked_path is None:
                missing.append(link)
                continue

            linked_content = self._read(linked_path)
            rel = linked_path.relative_to(self._vault)
            sections.append(f"\n---\n# Linked: {rel}\n\n{linked_content}")
            loaded += 1

        if missing:
            sections.append(
                f"\n---\n_Wikilinks with no matching note: {', '.join(missing)}_"
            )

        logger.info(
            f"[get_linked_notes] '{root_path.name}' → {loaded} linked notes loaded, {len(missing)} missing"
        )

        return ToolResult(
            success=True,
            output="\n".join(sections),
            metadata={
                "root":          str(root_path.relative_to(self._vault)),
                "links_found":   len(unique_links),
                "links_loaded":  loaded,
                "links_missing": missing,
            }
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve(self, name: str) -> Path | None:
        """Find a note by relative path or by stem name search."""
        # Try direct relative path
        candidate = self._vault / name
        if not candidate.suffix:
            candidate = candidate.with_suffix(".md")
        if candidate.exists():
            return candidate

        # Search by stem
        stem = Path(name).stem.lower()
        matches = [p for p in self._vault.rglob("*.md") if p.stem.lower() == stem]
        if len(matches) == 1:
            return matches[0]
        return None

    def _read(self, path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except Exception as exc:
            return f"[Could not read file: {exc}]"

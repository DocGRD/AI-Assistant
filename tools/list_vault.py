"""
Tool: list_vault
Lists the folder and note structure of the Obsidian vault.

Input:  Optional subfolder path to list (leave blank for vault root).
        Examples:
            ""                      <- list entire vault
            "Projects"              <- list only the Projects folder
            "Projects/Dairy-System" <- list a specific project

Output: An indented tree showing folders and .md files.
        Useful for understanding project structure before reading notes.
"""

import logging
from pathlib import Path

from tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")

EXCLUDED_DIRS  = {".obsidian", ".git", ".trash", ".venv"}
MAX_DEPTH      = 4    # how many folder levels to display
MAX_FILES      = 200  # safety cap — vaults can be large


class ListVaultTool(BaseTool):
    """Lists the folder/file structure of the vault (or a subfolder)."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "list_vault"

    @property
    def description(self) -> str:
        return "List the folder and note structure of the vault or a specific subfolder."

    def run(self, input_data: str) -> ToolResult:
        subfolder = input_data.strip()

        if subfolder:
            root = self._vault / subfolder
        else:
            root = self._vault

        if not root.exists():
            return ToolResult(
                success=False,
                output=f"Folder not found: '{subfolder}'"
            )

        lines: list[str] = []
        file_count = 0

        def walk(path: Path, depth: int, prefix: str) -> None:
            nonlocal file_count
            if depth > MAX_DEPTH or file_count >= MAX_FILES:
                return

            # Sort: folders first, then files, both alphabetically
            try:
                children = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
            except PermissionError:
                return

            for i, child in enumerate(children):
                if child.name in EXCLUDED_DIRS or child.name.startswith("."):
                    continue

                is_last = (i == len(children) - 1)
                connector = "└── " if is_last else "├── "
                extension = "│   " if not is_last else "    "

                if child.is_dir():
                    lines.append(f"{prefix}{connector}📁 {child.name}/")
                    walk(child, depth + 1, prefix + extension)
                elif child.suffix == ".md":
                    lines.append(f"{prefix}{connector}📄 {child.name}")
                    file_count += 1
                    if file_count >= MAX_FILES:
                        lines.append(f"{prefix}    ... (limit reached, use a subfolder path to see more)")
                        return

        display_root = subfolder if subfolder else "(vault root)"
        lines.append(f"📂 {display_root}")
        walk(root, depth=0, prefix="")

        if file_count == 0:
            lines.append("  (no markdown files found)")

        logger.info(f"[list_vault] Listed '{display_root}' — {file_count} notes")

        summary = f"\n{file_count} note(s) found."
        if file_count >= MAX_FILES:
            summary += f" Showing first {MAX_FILES} — refine with a subfolder path."

        return ToolResult(
            success=True,
            output="\n".join(lines) + summary,
            metadata={
                "root":       display_root,
                "file_count": file_count,
            }
        )

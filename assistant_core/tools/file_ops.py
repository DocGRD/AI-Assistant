"""
Vault file operations — Milestone 16.6 (slices 2-3).

Restructuring tools the agent lacked: copy a note or a whole folder tree, move/rename,
trash (recoverable — never hard-delete), and mkdir. Every path runs through
`paths.resolve_in_vault()` so it is jailed inside the vault root (`..`, absolute paths,
and symlink breakouts are rejected before any filesystem work).

These are **destructive / restructuring** ops. They execute when invoked as an explicit
`vault:` command (terminal or plugin), but are listed in `agent_loop.BLOCKED_COMMANDS`
so the agent can never run them autonomously — restructuring is always a human decision.

Two-path ops (copy, move) take `src -> dst` (also `=>`); a bare space-split would break
on real vault folders like "06 - Projects".
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path

from assistant_core.paths import resolve_in_vault
from assistant_core.tools.base_tool import BaseTool, ToolResult

logger = logging.getLogger("assistant")


def _split_two(raw: str) -> tuple[str, str] | None:
    """Parse `src -> dst` / `src => dst`. Returns (src, dst) or None if no separator."""
    for sep in ("->", "=>"):
        if sep in raw:
            a, b = raw.split(sep, 1)
            a, b = a.strip(), b.strip()
            if a and b:
                return a, b
    return None


class CopyPathTool(BaseTool):
    """Copy a note or an entire folder tree. Originals are untouched (low risk)."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "copy_path"

    @property
    def description(self) -> str:
        return "Copy a note or folder tree. Input: '<src> -> <dst>' (e.g. '06 - Projects -> 06 - Projects-backup')."

    def run(self, input_data: str) -> ToolResult:
        pair = _split_two(input_data or "")
        if not pair:
            return ToolResult(success=False, output="Usage: vault:copy <src> -> <dst>")
        try:
            src = resolve_in_vault(self._vault, pair[0])
            dst = resolve_in_vault(self._vault, pair[1])
        except ValueError as exc:
            return ToolResult(success=False, output=f"Rejected: {exc}")

        if not src.exists():
            return ToolResult(success=False, output=f"Source does not exist: {pair[0]}")
        if dst.exists():
            return ToolResult(success=False, output=f"Destination already exists: {pair[1]}")

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            if src.is_dir():
                shutil.copytree(src, dst)
                n = sum(1 for p in dst.rglob("*.md"))
                logger.info(f"[copy_path] folder {pair[0]} -> {pair[1]} ({n} notes)")
                return ToolResult(success=True,
                                  output=f"✓ Copied folder ({n} note(s)): {pair[0]} -> {pair[1]}",
                                  metadata={"kind": "folder", "notes": n})
            shutil.copy2(src, dst)
            logger.info(f"[copy_path] note {pair[0]} -> {pair[1]}")
            return ToolResult(success=True, output=f"✓ Copied note: {pair[0]} -> {pair[1]}",
                              metadata={"kind": "note"})
        except Exception as exc:
            logger.error(f"[copy_path] failed: {exc}")
            return ToolResult(success=False, output=f"Copy failed: {exc}")


class MovePathTool(BaseTool):
    """Move or rename a note or folder."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "move_path"

    @property
    def description(self) -> str:
        return "Move/rename a note or folder. Input: '<src> -> <dst>'."

    def run(self, input_data: str) -> ToolResult:
        pair = _split_two(input_data or "")
        if not pair:
            return ToolResult(success=False, output="Usage: vault:move <src> -> <dst>")
        try:
            src = resolve_in_vault(self._vault, pair[0])
            dst = resolve_in_vault(self._vault, pair[1])
        except ValueError as exc:
            return ToolResult(success=False, output=f"Rejected: {exc}")

        if not src.exists():
            return ToolResult(success=False, output=f"Source does not exist: {pair[0]}")
        if dst.exists():
            return ToolResult(success=False, output=f"Destination already exists: {pair[1]}")

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            logger.info(f"[move_path] {pair[0]} -> {pair[1]}")
            return ToolResult(success=True, output=f"✓ Moved: {pair[0]} -> {pair[1]}")
        except Exception as exc:
            logger.error(f"[move_path] failed: {exc}")
            return ToolResult(success=False, output=f"Move failed: {exc}")


class TrashPathTool(BaseTool):
    """Move a note or folder into the vault's `.trash/` (recoverable — never hard-delete)."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "trash_path"

    @property
    def description(self) -> str:
        return "Move a note or folder to .trash/ (recoverable). Input: '<path>'."

    def run(self, input_data: str) -> ToolResult:
        raw = (input_data or "").strip()
        if not raw:
            return ToolResult(success=False, output="Usage: vault:trash <path>")
        try:
            src = resolve_in_vault(self._vault, raw)
        except ValueError as exc:
            return ToolResult(success=False, output=f"Rejected: {exc}")

        if not src.exists():
            return ToolResult(success=False, output=f"Path does not exist: {raw}")

        rel = src.relative_to(self._vault.resolve())
        dst = self._vault / ".trash" / rel
        if dst.exists():   # keep a prior trashed copy — disambiguate with a timestamp
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            dst = dst.with_name(f"{dst.stem}-{stamp}{dst.suffix}")
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            trashed = str(dst.relative_to(self._vault.resolve())).replace("\\", "/")
            logger.info(f"[trash_path] {raw} -> {trashed}")
            return ToolResult(success=True, output=f"✓ Trashed (recoverable): {raw} -> {trashed}",
                              metadata={"trashed_to": trashed})
        except Exception as exc:
            logger.error(f"[trash_path] failed: {exc}")
            return ToolResult(success=False, output=f"Trash failed: {exc}")


class MkdirTool(BaseTool):
    """Create a folder (and any parents) inside the vault."""

    def __init__(self, vault_path: str):
        self._vault = Path(vault_path)

    @property
    def name(self) -> str:
        return "mkdir_vault"

    @property
    def description(self) -> str:
        return "Create a folder (with parents) in the vault. Input: '<path>'."

    def run(self, input_data: str) -> ToolResult:
        raw = (input_data or "").strip()
        if not raw:
            return ToolResult(success=False, output="Usage: vault:mkdir <path>")
        try:
            target = resolve_in_vault(self._vault, raw)
        except ValueError as exc:
            return ToolResult(success=False, output=f"Rejected: {exc}")
        if target.exists():
            return ToolResult(success=False, output=f"Already exists: {raw}")
        try:
            target.mkdir(parents=True, exist_ok=False)
            logger.info(f"[mkdir_vault] {raw}")
            return ToolResult(success=True, output=f"✓ Folder created: {raw}")
        except Exception as exc:
            logger.error(f"[mkdir_vault] failed: {exc}")
            return ToolResult(success=False, output=f"mkdir failed: {exc}")

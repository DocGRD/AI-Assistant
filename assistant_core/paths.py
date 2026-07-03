"""Single source of truth for the service's on-disk locations.

Before the package reorg these were scattered as fragile ``Path(__file__).parent``
chains across app/logger/service. Centralizing them here means the depth of a
module inside the package no longer matters.

Layout:
    REPO_ROOT/                  repo root (also the systemd WorkingDirectory)
    ├── assistant_core/         this package  (PACKAGE_DIR)
    │   └── config/             config_manager + settings.json  (CONFIG_DIR)
    ├── logs/                   rotating logs  (LOGS_DIR)
    ├── data/                   per-machine RAG index, rebuildable  (DATA_DIR)
    └── tests/                  test suite (run from REPO_ROOT)

logs/ and data/ are deliberately anchored at the repo root (not inside the
package) so an existing deployment keeps writing to the same place.
"""

import re
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent          # .../assistant_core
REPO_ROOT   = PACKAGE_DIR.parent                        # repo root
CONFIG_DIR  = PACKAGE_DIR / "config"                    # settings live with the package
LOGS_DIR    = REPO_ROOT / "logs"
DATA_DIR    = REPO_ROOT / "data"


def resolve_in_vault(vault, rel: str) -> Path:
    """Resolve a vault-relative path and guarantee it stays inside the vault root.

    Normalises backslashes, then `.resolve()`s (which also collapses `..` and follows
    symlinks) and verifies the result is the vault root or a descendant of it. Raises
    ``ValueError`` on any escape — `..` traversal, an absolute path, or a symlink
    breakout. Shared by every M16.6 write op (copy/move/trash/mkdir) so the path jail
    is defined in exactly one place."""
    vault = Path(vault).resolve()
    raw = str(rel).replace("\\", "/").strip()
    # Reject a Windows drive-letter absolute path (e.g. "C:/…") on EVERY OS — on Linux it
    # isn't recognised as absolute, so without this it would be treated as a vault-relative
    # folder instead of being refused. (POSIX "/…" is defanged by the strip below.)
    if re.match(r"^[A-Za-z]:(/|$)", raw):
        raise ValueError(f"path escapes the vault: {rel!r}")
    rel_norm = raw.strip("/")
    if not rel_norm:
        raise ValueError("empty path")
    candidate = (vault / rel_norm).resolve()
    if candidate != vault and vault not in candidate.parents:
        raise ValueError(f"path escapes the vault: {rel!r}")
    return candidate


def is_vault(path) -> bool:
    """True only if `path` is a real Obsidian vault — an existing directory with a
    `.obsidian/` folder. Guards against creating/seeding the AI/ structure into a
    typo'd or non-vault directory (T3.20). Lives here (no first-party deps) so both
    the bootstrap and the provider registry loader can use it without import cycles."""
    if not path:
        return False
    p = Path(path)
    return p.is_dir() and (p / ".obsidian").is_dir()

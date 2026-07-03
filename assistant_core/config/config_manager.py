"""
Configuration Manager
Loads and provides access to settings.json.
"""

import json
from pathlib import Path


class ConfigManager:
    """Loads settings.json and provides get() access to every key."""

    @staticmethod
    def _resolve_default(pkg: Path, root: Path) -> Path:
        """Prefer the in-package settings, but fall back to the repo-root ``config/``
        location (where pre-reorg installs keep it). Returns whichever exists — pkg wins
        when both do — so the caller still gets a clear error if neither is present."""
        return pkg if pkg.exists() else root

    def __init__(self, settings_path: Path | None = None):
        if settings_path is None:
            # New canonical path is next to this module; older deployments (before the
            # assistant_core/ reorg) keep settings.json at <repo>/config/settings.json.
            settings_path = self._resolve_default(
                Path(__file__).parent / "settings.json",
                Path(__file__).resolve().parents[2] / "config" / "settings.json",
            )

        self._path = Path(settings_path)
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(
                f"Settings file not found: {self._path}\n"
                "Create assistant_core/config/settings.json (or config/settings.json) "
                "before starting the assistant."
            )
        with open(self._path, "r", encoding="utf-8") as fh:
            self._data = json.load(fh)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def all(self) -> dict:
        return dict(self._data)

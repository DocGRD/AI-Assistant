"""
Configuration Manager
Loads and provides access to settings.json.
"""

import json
from pathlib import Path


class ConfigManager:
    """Loads settings.json and provides get() access to every key."""

    def __init__(self, settings_path: Path | None = None):
        if settings_path is None:
            settings_path = Path(__file__).parent / "settings.json"

        self._path = settings_path
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(
                f"Settings file not found: {self._path}\n"
                "Create config/settings.json before starting the assistant."
            )
        with open(self._path, "r", encoding="utf-8") as fh:
            self._data = json.load(fh)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def all(self) -> dict:
        return dict(self._data)

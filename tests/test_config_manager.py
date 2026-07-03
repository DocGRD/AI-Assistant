"""ConfigManager — path resolution (package path vs repo-root fallback). Stdlib unittest."""

import json
import tempfile
import unittest
from pathlib import Path

from assistant_core.config.config_manager import ConfigManager


class ResolveDefaultTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.d = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_prefers_package_path_when_present(self):
        pkg = self.d / "pkg.json"; pkg.write_text("{}", encoding="utf-8")
        root = self.d / "root.json"; root.write_text("{}", encoding="utf-8")
        self.assertEqual(ConfigManager._resolve_default(pkg, root), pkg)

    def test_falls_back_to_repo_root_when_package_missing(self):
        pkg = self.d / "pkg.json"                      # does not exist
        root = self.d / "root.json"; root.write_text("{}", encoding="utf-8")
        self.assertEqual(ConfigManager._resolve_default(pkg, root), root)

    def test_returns_pkg_when_neither_exists(self):
        # Neither present → return pkg so _load raises the clear FileNotFoundError.
        pkg = self.d / "pkg.json"
        root = self.d / "root.json"
        self.assertEqual(ConfigManager._resolve_default(pkg, root), root)  # pkg missing → root


class ExplicitPathTests(unittest.TestCase):
    def test_loads_explicit_settings_file(self):
        with tempfile.TemporaryDirectory() as t:
            p = Path(t) / "settings.json"
            p.write_text(json.dumps({"vault_path": "/x", "port": 8765}), encoding="utf-8")
            cfg = ConfigManager(settings_path=p)
            self.assertEqual(cfg.get("port"), 8765)
            self.assertEqual(cfg.get("missing", "dflt"), "dflt")

    def test_missing_file_raises(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(FileNotFoundError):
                ConfigManager(settings_path=Path(t) / "nope.json")


if __name__ == "__main__":
    unittest.main()

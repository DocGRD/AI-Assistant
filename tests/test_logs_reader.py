"""Tests for v1.9 vault:logs self-diagnosis (reads logs/assistant.log outside the vault)."""

import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from assistant_core import logs_reader


class TestLogsReader(unittest.TestCase):
    def _patch_logs(self, tmp: Path):
        return mock.patch("assistant_core.paths.LOGS_DIR", tmp)

    def test_tail_default_and_n(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "assistant.log").write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")
        with self._patch_logs(tmp):
            self.assertEqual(len(logs_reader.read_logs("")["lines"]), logs_reader.DEFAULT_TAIL)
            self.assertEqual(len(logs_reader.read_logs("10")["lines"]), 10)
            self.assertEqual(logs_reader.read_logs("5")["lines"][-1], "line 199")

    def test_errors_filter(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "assistant.log").write_text(
            "2026-07-09 10:00:00 | INFO     | ok\n"
            "2026-07-09 10:00:01 | ERROR    | boom\n"
            "2026-07-09 10:00:02 | WARNING  | careful\n", encoding="utf-8")
        with self._patch_logs(tmp):
            lines = logs_reader.read_logs("errors")["lines"]
        self.assertEqual(len(lines), 2)
        self.assertTrue(any("boom" in l for l in lines))
        self.assertFalse(any("| INFO" in l for l in lines))

    def test_today_filter(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        today = datetime.now().strftime("%Y-%m-%d")
        (tmp / "assistant.log").write_text(
            f"{today} 09:00:00 | INFO | today-line\n"
            "2000-01-01 09:00:00 | INFO | old-line\n", encoding="utf-8")
        with self._patch_logs(tmp):
            lines = logs_reader.read_logs("today")["lines"]
        self.assertEqual(lines, [f"{today} 09:00:00 | INFO | today-line"])

    def test_no_log_file(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        with self._patch_logs(tmp):
            rep = logs_reader.read_logs("")
        self.assertTrue(rep["error"])
        self.assertIn("Logs:", logs_reader.format_reply(rep))


if __name__ == "__main__":
    unittest.main()

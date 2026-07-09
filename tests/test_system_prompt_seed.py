"""v1.9 — the System-Prompt is packaged + version-stamped + self-seeding, and must mention every
command in the canonical reference (anti-drift: this is why M34–M40 went missing before)."""

import re
import tempfile
import unittest
from pathlib import Path

from assistant_core.memory.memory_manager import (
    MemoryManager, PROMPT_VERSION, _packaged_system_prompt, _PROMPT_STAMP,
)

_SEED = Path(__file__).resolve().parents[1] / "assistant_core" / "seed"


class TestSystemPromptSeed(unittest.TestCase):
    def _mm(self) -> tuple[MemoryManager, Path]:
        v = Path(tempfile.mkdtemp())
        (v / "AI" / "System").mkdir(parents=True, exist_ok=True)
        return MemoryManager(str(v)), v

    def test_packaged_prompt_exists_and_is_stamped(self):
        p = _packaged_system_prompt()
        self.assertTrue(p)
        m = _PROMPT_STAMP.search(p)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group(1)), PROMPT_VERSION)

    def test_prompt_lists_every_command_in_the_reference(self):
        """Every `vault:<cmd>` documented in seed/help/Commands.md must appear in the System-Prompt."""
        prompt = _packaged_system_prompt()
        commands_md = (_SEED / "help" / "Commands.md").read_text(encoding="utf-8")
        ref = set(re.findall(r"vault:[a-z-]+", commands_md)) - {"vault:"}
        missing = sorted(c for c in ref if c not in prompt)
        self.assertEqual(missing, [], f"System-Prompt is missing commands: {missing}")

    def test_new_v19_commands_present(self):
        prompt = _packaged_system_prompt()
        for cmd in ("vault:logs", "vault:goal", "vault:analytics", "vault:clip", "vault:template",
                    "vault:briefing", "vault:organize", "vault:moc", "vault:actions"):
            self.assertIn(cmd, prompt, f"{cmd} not documented in the System-Prompt")

    def test_seed_writes_when_missing_then_skips(self):
        mm, v = self._mm()
        self.assertTrue(mm.seed_system_prompt())          # fresh → writes
        self.assertFalse(mm.seed_system_prompt())         # current → no-op
        dest = v / "AI" / "System" / "System-Prompt.md"
        self.assertIn(f"prompt-version: {PROMPT_VERSION}", dest.read_text(encoding="utf-8"))

    def test_stale_prompt_is_refreshed_and_backed_up(self):
        mm, v = self._mm()
        dest = v / "AI" / "System" / "System-Prompt.md"
        dest.write_text("<!-- prompt-version: 0 -->\nMY OLD CUSTOM PROMPT\n", encoding="utf-8")
        self.assertTrue(mm.seed_system_prompt())          # older stamp → rewrites
        self.assertIn("vault:logs", dest.read_text(encoding="utf-8"))
        bak = v / "AI" / "System" / "System-Prompt.bak-v0.md"
        self.assertTrue(bak.exists())
        self.assertIn("MY OLD CUSTOM PROMPT", bak.read_text(encoding="utf-8"))

    def test_load_system_prompt_returns_current(self):
        mm, v = self._mm()
        text = mm.load_system_prompt()
        self.assertIn("vault:logs", text)
        self.assertIn("vault:goal", text)


if __name__ == "__main__":
    unittest.main()

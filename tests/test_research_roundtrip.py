"""M20 — shared research round-trip helper (hardened, T5.01). Stdlib unittest."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from assistant_core.research_roundtrip import (
    save_research_verbatim, summarize_research, append_related_notes, generate_note_title,
)


class SaveVerbatimTests(unittest.TestCase):
    def test_returns_saved_path(self):
        class _Reg:
            def run(self, tool, inp):
                assert tool == "import_research"
                return SimpleNamespace(success=True, metadata={"path": "AI/Research/x.md"})
        self.assertEqual(save_research_verbatim(_Reg(), "text"), "AI/Research/x.md")

    def test_none_registry_or_failure(self):
        self.assertIsNone(save_research_verbatim(None, "text"))
        class _Reg:
            def run(self, tool, inp):
                return SimpleNamespace(success=False, metadata=None)
        self.assertIsNone(save_research_verbatim(_Reg(), "text"))


class SummarizeTests(unittest.TestCase):
    def test_single_non_agentic_call(self):
        calls = {"n": 0, "private": None}
        class _Router:
            def generate(self, messages, system_prompt="", private=False, **kw):
                calls["n"] += 1
                calls["private"] = private
                return "A rocket mass heater stores heat in thermal mass.", "groq"
        out = summarize_research(_Router(), "how do RMH work", "long research text", private=True)
        self.assertIn("thermal mass", out)
        self.assertEqual(calls["n"], 1)            # exactly one call — no agent loop
        self.assertTrue(calls["private"])

    def test_no_router_or_failure_returns_empty(self):
        self.assertEqual(summarize_research(None, "q", "t"), "")
        class _Bad:
            def generate(self, **kw): raise RuntimeError("down")
        with self.assertLogs("assistant", level="WARNING"):     # failure is expected
            self.assertEqual(summarize_research(_Bad(), "q", "t"), "")


class GenerateTitleTests(unittest.TestCase):
    def test_single_call_capped_to_four_words_and_forces_private(self):
        calls = {"n": 0, "private": None}
        class _Router:
            def generate(self, messages, system_prompt="", private=False, **kw):
                calls["n"] += 1
                calls["private"] = private
                return "Rocket Mass Heater Design", "groq"
        title = generate_note_title(_Router(), "long research text about rocket mass heaters")
        self.assertEqual(title, "Rocket Mass Heater Design")
        self.assertEqual(calls["n"], 1)
        self.assertTrue(calls["private"])           # forced private — unknown caller context

    def test_caps_a_rambling_reply_to_four_words(self):
        class _Router:
            def generate(self, messages, system_prompt="", **kw):
                return "This Is Way Too Many Words For A Title", "groq"
        self.assertEqual(generate_note_title(_Router(), "x").split(),
                         ["This", "Is", "Way", "Too"])

    def test_no_router_or_empty_reply_returns_none(self):
        self.assertIsNone(generate_note_title(None, "x"))
        class _Empty:
            def generate(self, **kw): return "", "groq"
        self.assertIsNone(generate_note_title(_Empty(), "x"))

    def test_failure_returns_none(self):
        class _Bad:
            def generate(self, **kw): raise RuntimeError("down")
        with self.assertLogs("assistant", level="WARNING"):     # failure is expected
            self.assertIsNone(generate_note_title(_Bad(), "x"))


class _FakeRag:
    """relevant_notes returns REAL paths; enabled toggles availability."""
    def __init__(self, paths, enabled=True):
        self.enabled = enabled
        self._paths = paths
    def relevant_notes(self, note_path, k=5):
        return [{"path": p, "score": 0.9} for p in self._paths]


class RelatedNotesTests(unittest.TestCase):
    def test_appends_only_real_index_neighbours(self):
        with tempfile.TemporaryDirectory() as d:
            note = Path(d) / "AI/Research/r.md"
            note.parent.mkdir(parents=True, exist_ok=True)
            note.write_text("# R\n\nbody\n", encoding="utf-8")
            rag = _FakeRag(["06 - Projects/Rocket-Stove.md", "AI/Research/Masonry.md"])
            linked = append_related_notes(rag, d, "AI/Research/r.md")
            self.assertEqual(len(linked), 2)
            body = note.read_text(encoding="utf-8")
            self.assertIn("## Related notes", body)
            self.assertIn("[[06 - Projects/Rocket-Stove]]", body)   # real, .md stripped

    def test_no_rag_or_disabled_appends_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            note = Path(d) / "r.md"; note.write_text("x", encoding="utf-8")
            self.assertEqual(append_related_notes(None, d, "r.md"), [])
            self.assertEqual(append_related_notes(_FakeRag([], enabled=False), d, "r.md"), [])
            self.assertNotIn("Related notes", note.read_text(encoding="utf-8"))

    def test_empty_neighbours_appends_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            note = Path(d) / "r.md"; note.write_text("x", encoding="utf-8")
            self.assertEqual(append_related_notes(_FakeRag([]), d, "r.md"), [])
            self.assertNotIn("Related notes", note.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

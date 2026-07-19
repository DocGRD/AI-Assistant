"""
Automated coverage for M4 (Router + Memory), the deterministic parts:
memory structure + profile/facts loading (T4.05/06/08), remember: (T4.07/09),
episode logging incl. crash-safe live writes (T4.10-T4.15, T4.20), and the
context-window manager (T4.16-T4.18). Routing (T4.01-T4.04) lives in
test_routing.py. The LLM-behaviour tests (T4.21/22) and the hard-kill (T4.19)
stay manual. Stdlib unittest, no network.
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from assistant_core.memory.memory_manager import MemoryManager
from assistant_core.memory.context_manager import ContextManager
from assistant_core.episodes import ep_vault, ep_remember, ep_chat
from assistant_core.providers.base_provider import Message
from assistant_core.providers.model_registry import estimate_tokens


class _MM(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        self.mm = MemoryManager(str(self.vault))

    def tearDown(self):
        self._tmp.cleanup()


class MemoryStructureTests(_MM):
    def test_structure_created_on_first_run(self):          # T4.05
        self.assertTrue((self.vault / "AI/Memory/User-Profile.md").exists())
        self.assertTrue((self.vault / "AI/Memory/Facts/Learned-Facts.md").exists())
        self.assertTrue((self.vault / "AI/Memory/Projects").is_dir())
        self.assertTrue((self.vault / "AI/Memory/Episodes").is_dir())


class ContextLoadTests(_MM):
    def test_profile_loaded_into_context(self):             # T4.06
        (self.vault / "AI/Memory/User-Profile.md").write_text(
            "# User Profile\n\nMy favourite colour is teal.\n", encoding="utf-8")
        ctx = self.mm.load_context()
        self.assertIn("User Profile", ctx)
        self.assertIn("teal", ctx)

    def test_remembered_fact_available_next_session(self):  # T4.08
        self.mm.remember("The rocket stove riser is 30cm")
        fresh = MemoryManager(str(self.vault))              # simulate a new session
        self.assertIn("rocket stove riser is 30cm", fresh.load_context())


class RememberTests(_MM):
    def test_remember_writes_immediately_with_timestamp(self):   # T4.07
        msg = self.mm.remember("The test vault has 200+ notes")
        self.assertTrue(msg.startswith("✓"))           # ✓ Remembered
        facts = (self.vault / "AI/Memory/Facts/Learned-Facts.md").read_text(encoding="utf-8")
        self.assertIn("The test vault has 200+ notes", facts)
        self.assertRegex(facts, r"- \[\d{4}-\d{2}-\d{2} \d{2}:\d{2}\]")   # timestamped

    def test_empty_remember_is_graceful(self):              # T4.09
        before = (self.vault / "AI/Memory/Facts/Learned-Facts.md").read_text(encoding="utf-8")
        msg = self.mm.remember("   ")
        self.assertIn("Nothing to remember", msg)
        after = (self.vault / "AI/Memory/Facts/Learned-Facts.md").read_text(encoding="utf-8")
        self.assertEqual(before, after)                     # nothing written


class EpisodeTests(_MM):
    def _ep_text(self) -> str:
        files = list((self.vault / "AI/Memory/Episodes").glob("*.md"))
        self.assertEqual(len(files), 1)
        return files[0].read_text(encoding="utf-8")

    def test_episode_created_with_header(self):             # T4.10
        self.mm.open_episode()
        text = self._ep_text()
        self.assertIn("# Episode", text)
        self.assertIn("## Session", text)

    def test_live_append_is_immediate(self):                # T4.11 (+ crash-safety mechanism, T4.19)
        self.mm.open_episode()
        self.mm.append_episode("- a live line")
        self.assertIn("- a live line", self._ep_text())     # present without close()

    def test_vault_and_remember_and_chat_lines(self):       # T4.12 / T4.13 / T4.20
        self.mm.open_episode()
        self.mm.append_episode(ep_vault("search_vault", "test"))
        self.mm.append_episode(ep_remember("a fact"))
        self.mm.append_episode(ep_chat("hi", "hello there", provider="groq"))
        text = self._ep_text()
        self.assertIn("`search_vault`", text)
        self.assertIn("test", text)
        self.assertIn("Remembered: a fact", text)
        self.assertIn("[groq]", text)                       # provider tag in chat line

    def test_footer_on_close(self):                         # T4.14
        self.mm.open_episode()
        self.mm.append_episode(ep_vault("search_vault", "x"))
        self.mm.close_episode(tools_used=["search_vault"])
        text = self._ep_text()
        self.assertIn("**Session ended:**", text)
        self.assertIn("search_vault", text)

    def test_second_session_appends_with_divider(self):     # T4.15
        self.mm.open_episode(); self.mm.close_episode()
        self.mm.open_episode()                              # same day → same file
        text = self._ep_text()
        self.assertEqual(text.count("## Session"), 2)
        self.assertIn("---", text)


class _FakeReg:
    """Tiny model registry for the context manager (tpm 1000, ctx 4000)."""
    def spec(self, name):
        return SimpleNamespace(tpm_limit=1000, context_window=4000)


class ContextManagerTests(unittest.TestCase):
    def _history(self, pairs: int, size: int = 240):
        h = []
        for i in range(pairs):
            h.append(Message(role="user", content=f"u{i} " + "x" * size))
            h.append(Message(role="assistant", content=f"a{i} " + "y" * size))
        return h

    def test_trims_when_over_threshold(self):               # T4.16 / T4.17
        cm = ContextManager(_FakeReg())
        history = self._history(8)                          # > MIN_CHAT_TURNS pairs, well over 800-token limit
        before = estimate_tokens(history, "SYS")
        self.assertGreater(before, 800)
        trimmed = cm.trim(history, "groq", "SYS", max_response_tokens=256)
        after = estimate_tokens(trimmed, "SYS")
        self.assertLess(after, before)                      # trimming reduced the token estimate

    def test_no_trim_when_small(self):
        cm = ContextManager(_FakeReg())
        history = self._history(1, size=10)                 # tiny → under limit
        self.assertEqual(cm.trim(history, "groq", "SYS"), history)

    def test_report_format(self):                           # T4.18
        cm = ContextManager(_FakeReg())
        rep = cm.report(self._history(2), "groq", "SYS")
        self.assertIn("tokens in history", rep)
        self.assertIn("%", rep)


class _SummaryRouter:
    """Stands in for the provider router during context summarization."""
    def __init__(self, reply="Earlier: user asked about rocket heaters; agreed to use cob.", fail=False):
        self.reply, self.fail = reply, fail
        self.calls, self.last_private = 0, None

    def generate(self, messages, system_prompt="", private=False, **kw):
        self.calls += 1
        self.last_private = private
        if self.fail:
            raise RuntimeError("provider down")
        return self.reply, "groq"


class ContextSummarizationTests(unittest.TestCase):   # M17 Slice 5
    def _history(self, pairs, size=240):
        h = []
        for i in range(pairs):
            h.append(Message(role="user", content=f"u{i} " + "x" * size))
            h.append(Message(role="assistant", content=f"a{i} " + "y" * size))
        return h

    def test_summarizes_instead_of_stubbing(self):
        router = _SummaryRouter()
        cm = ContextManager(_FakeReg(), router=router, config={"cloud_summarization": True})
        trimmed = cm.trim(self._history(8), "groq", "SYS", max_response_tokens=256, private=True)
        joined = "\n".join(m.content for m in trimmed)
        self.assertIn("[Summary of earlier conversation:", joined)
        self.assertNotIn("[Older message trimmed", joined)   # used summary, not the lossy stub
        self.assertGreaterEqual(router.calls, 1)
        self.assertTrue(router.last_private)                  # privacy carried into the summarizer

    def test_legacy_context_summarization_alias(self):
        # The old key name still works (backward-compat) and behaves like cloud_summarization.
        router = _SummaryRouter()
        cm = ContextManager(_FakeReg(), router=router, config={"context_summarization": True})
        trimmed = cm.trim(self._history(8), "groq", "SYS", max_response_tokens=256)
        joined = "\n".join(m.content for m in trimmed)
        self.assertIn("[Summary of earlier conversation:", joined)
        self.assertGreaterEqual(router.calls, 1)

    def test_falls_back_to_trim_on_failure(self):
        router = _SummaryRouter(fail=True)
        cm = ContextManager(_FakeReg(), router=router, config={"cloud_summarization": True})
        with self.assertLogs("assistant", level="WARNING"):   # summariser failure is expected
            trimmed = cm.trim(self._history(8), "groq", "SYS", max_response_tokens=256)
        joined = "\n".join(m.content for m in trimmed)
        self.assertIn("[Older message trimmed", joined)       # graceful fallback to the stub trim

    def test_disabled_uses_trim(self):
        router = _SummaryRouter()
        cm = ContextManager(_FakeReg(), router=router, config={"cloud_summarization": False})
        cm.trim(self._history(8), "groq", "SYS", max_response_tokens=256)
        self.assertEqual(router.calls, 0)                     # opt-in: no LLM call when disabled


if __name__ == "__main__":
    unittest.main()

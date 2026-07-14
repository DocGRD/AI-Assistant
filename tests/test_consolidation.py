"""M17 — dreaming & consolidation engine + nightly scheduler decision. Stdlib unittest."""

import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from assistant_core import consolidation as C
from assistant_core.consolidation import ConsolidationEngine
from assistant_core.scheduler import consolidate_due


class _FakeRouter:
    """Returns a canned bullet list of facts; records that it was asked privately."""
    def __init__(self, reply="- The user heats with a rocket mass heater\n- Project Camping is active"):
        self.reply = reply
        self.private_calls = 0

    def generate(self, messages, system_prompt="", private=False, **kw):
        if private:
            self.private_calls += 1
        return self.reply, "groq"


class _FakeEmbedder:
    """Deterministic: identical text → identical vector, so dedupe is exact-ish."""
    def embed(self, texts):
        import numpy as np
        return np.array([[float(sum(bytearray(t.lower().encode()))), float(len(t))] for t in texts])


class ParsingTests(unittest.TestCase):
    def test_parse_facts_and_none(self):
        self.assertEqual(C.parse_facts("- a\n- b"), ["a", "b"])
        self.assertEqual(C.parse_facts("NONE"), [])
        self.assertEqual(C.parse_facts("Some prose, no bullets."), [])

    def test_transient_facts_filtered(self):
        # Self-referential facts about Loremaster's own operation must be dropped (they were
        # polluting consolidation proposals with debug-session artifacts).
        for junk in ["There are 408 orphan notes in the vault",
                     "Episodes are archived when they are older than 30 days",
                     "The vault:analytics command can identify orphan notes",
                     "The episodes were not archived because consolidate was not run"]:
            self.assertTrue(C._looks_transient(junk), junk)
        for real in ["The user is studying the biblical book of 1 John",
                     "Glenn has a background in embedded systems"]:
            self.assertFalse(C._looks_transient(real), real)

    def test_existing_facts_strips_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            fp = Path(d) / C.FACTS_FILE
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text("- [2026-06-01 10:00] likes tea\n- plain fact\n", encoding="utf-8")
            self.assertEqual(C.existing_facts(d), ["likes tea", "plain fact"])


class DedupeTests(unittest.TestCase):
    def test_exact_text_is_duplicate_without_embedder(self):
        new, dups = C.dedupe_against_existing(["Likes Tea", "new one"], ["likes tea"], None)
        self.assertIn("new one", new)
        self.assertIn("Likes Tea", dups)

    def test_embedder_suppresses_near_dup(self):
        emb = _FakeEmbedder()
        # identical strings → identical vectors → cosine 1.0 ≥ threshold → duplicate
        new, dups = C.dedupe_against_existing(["likes tea"], ["likes tea"], emb)
        self.assertEqual(new, [])
        self.assertEqual(dups, ["likes tea"])


class EngineTests(unittest.TestCase):
    def _vault_with_episode(self, d, day="2026-06-01", body="User decided to use a rocket mass heater."):
        ep = Path(d) / C.EPISODES_DIR / f"{day}.md"
        ep.parent.mkdir(parents=True, exist_ok=True)
        ep.write_text(f"# Episode — {day}\n\n{body}\n", encoding="utf-8")

    def test_run_writes_proposal_and_forces_private(self):
        with tempfile.TemporaryDirectory() as d:
            self._vault_with_episode(d)
            router = _FakeRouter()
            report = ConsolidationEngine(d, router).run(apply=False)
            self.assertEqual(report["days"], ["2026-06-01"])
            self.assertTrue(report["new_facts"])
            self.assertGreaterEqual(router.private_calls, 1)        # extraction was forced private
            proposed = Path(d) / report["proposal"]
            self.assertTrue(proposed.exists())
            self.assertIn("Proposed new facts", proposed.read_text(encoding="utf-8"))
            # live memory untouched unless apply
            self.assertFalse((Path(d) / C.FACTS_FILE).exists())

    def test_apply_appends_to_learned_facts(self):
        with tempfile.TemporaryDirectory() as d:
            self._vault_with_episode(d)
            report = ConsolidationEngine(d, _FakeRouter()).run(apply=True)
            self.assertTrue(report["applied"])
            facts = (Path(d) / C.FACTS_FILE).read_text(encoding="utf-8")
            self.assertIn("consolidated]", facts)

    def test_watermark_prevents_reprocessing(self):
        with tempfile.TemporaryDirectory() as d:
            self._vault_with_episode(d, day="2026-06-01")
            ConsolidationEngine(d, _FakeRouter()).run()
            # second run: same episode is now behind the watermark → no days processed
            report2 = ConsolidationEngine(d, _FakeRouter()).run()
            self.assertEqual(report2["days"], [])

    def test_current_day_is_not_consolidated(self):
        with tempfile.TemporaryDirectory() as d:
            today = datetime.now().strftime("%Y-%m-%d")
            self._vault_with_episode(d, day=today)
            report = ConsolidationEngine(d, _FakeRouter()).run()
            self.assertEqual(report["days"], [])                    # in-progress day skipped


class ArchivalTests(unittest.TestCase):
    def _episode(self, d, day, body="x"):
        ep = Path(d) / C.EPISODES_DIR / f"{day}.md"
        ep.parent.mkdir(parents=True, exist_ok=True)
        ep.write_text(f"# Episode — {day}\n\n## Session — 10:00\n\n{body}\n", encoding="utf-8")

    def test_moves_old_and_keeps_recent(self):
        with tempfile.TemporaryDirectory() as d:
            self._episode(d, "2026-05-01")   # old
            self._episode(d, "2026-06-28")   # recent
            rep = C.archive_old_episodes(d, keep_days=30, today="2026-06-30")
            self.assertIn("2026-05-01", rep["archived"])
            self.assertNotIn("2026-06-28", rep["archived"])
            # old one moved to Archive, recent one stays
            self.assertFalse((Path(d) / C.EPISODES_DIR / "2026-05-01.md").exists())
            self.assertTrue((Path(d) / C.ARCHIVE_DIR / "2026-05-01.md").exists())
            self.assertTrue((Path(d) / C.EPISODES_DIR / "2026-06-28.md").exists())
            digest = (Path(d) / C.ARCHIVE_DIR / "digest-2026-05.md").read_text(encoding="utf-8")
            self.assertIn("[[2026-05-01]]", digest)

    def test_archive_folder_is_not_reprocessed(self):
        with tempfile.TemporaryDirectory() as d:
            self._episode(d, "2026-05-01")
            C.archive_old_episodes(d, keep_days=30, today="2026-06-30")
            # episode_files_since uses a non-recursive glob → Archive/ files are invisible
            files = C.episode_files_since(d, "", before="2026-06-30")
            self.assertEqual(files, [])

    def test_engine_run_archives_when_requested(self):
        with tempfile.TemporaryDirectory() as d:
            ep = Path(d) / C.EPISODES_DIR / "2026-05-01.md"
            ep.parent.mkdir(parents=True, exist_ok=True)
            ep.write_text("# Episode\n\n## Session\n\nUser likes rocket heaters.\n", encoding="utf-8")
            rep = ConsolidationEngine(d, _FakeRouter()).run(archive_days=30)
            self.assertIn("2026-05-01", rep["archived"])


class ProposalReviewTests(unittest.TestCase):       # M17 Slice 4
    def _proposal(self, d, name="consolidation-2026-06-29.md"):
        p = Path(d) / C.PROPOSED_DIR / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            "# Memory consolidation proposal\n\n## Proposed new facts\n\n"
            "- [ ] The user heats with a rocket mass heater\n"
            "- [ ] Project Camping is active\n", encoding="utf-8")
        return p

    def test_list_proposals_parses_facts(self):
        with tempfile.TemporaryDirectory() as d:
            self._proposal(d)
            props = C.list_proposals(d)
            self.assertEqual(len(props), 1)
            self.assertIn("The user heats with a rocket mass heater", props[0]["facts"])
            self.assertEqual(len(props[0]["facts"]), 2)

    def test_apply_proposal_appends_and_resolves(self):
        with tempfile.TemporaryDirectory() as d:
            p = self._proposal(d)
            res = C.apply_proposal(d, "consolidation-2026-06-29.md",
                                   ["The user heats with a rocket mass heater"])
            self.assertEqual(res["applied"], 1)
            self.assertTrue(res["resolved"])
            self.assertFalse(p.exists())                      # proposal removed after review
            facts = (Path(d) / C.FACTS_FILE).read_text(encoding="utf-8")
            self.assertIn("rocket mass heater", facts)
            self.assertNotIn("Project Camping", facts)        # rejected fact not added

    def test_apply_proposal_is_path_jailed(self):
        with tempfile.TemporaryDirectory() as d:
            self._proposal(d)
            # a traversal filename collapses to its basename → stays in the proposals dir
            res = C.apply_proposal(d, "../../etc/consolidation-2026-06-29.md", [])
            self.assertTrue(res["resolved"])                  # resolved the real proposal, no escape


class ConsolidateDueTests(unittest.TestCase):
    def test_fires_once_per_night(self):
        now = datetime(2026, 7, 15, 4, 0, 0)
        self.assertFalse(consolidate_due(now, 4, "2026-07-15"))     # already fired today
        self.assertTrue(consolidate_due(now, 4, "2026-07-14"))      # last fired yesterday
        self.assertTrue(consolidate_due(now, 4, None))              # never fired
        self.assertFalse(consolidate_due(datetime(2026, 7, 15, 9), 4, None))  # wrong hour


if __name__ == "__main__":
    unittest.main()

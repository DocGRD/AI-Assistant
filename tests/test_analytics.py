"""M38 — vault analytics: orphans, stale, tags, most-linked, unsourced, tag-merges."""

import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from assistant_core import analytics


class _Embedder:
    """Fake: #prayer and #prayers embed identically; others orthogonal."""
    def embed(self, texts):
        import numpy as np
        out = []
        for t in texts:
            base = t.rstrip("s").strip()
            v = np.zeros(8, dtype="float32")
            v[hash(base) % 8] = 1.0
            out.append(v)
        return np.array(out)


class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        (v / "Hub.md").write_text("A hub. #prayer", encoding="utf-8")
        (v / "Spoke.md").write_text("Links to [[Hub]]. #prayers", encoding="utf-8")
        (v / "Lonely.md").write_text("Nothing links here and it links nowhere.", encoding="utf-8")

    def test_orphans(self):
        orph = analytics.orphans(self.tmp)
        self.assertIn("Lonely.md", orph)
        self.assertNotIn("Hub.md", orph)
        self.assertNotIn("Spoke.md", orph)

    def test_most_linked(self):
        ml = dict(analytics.most_linked(self.tmp))
        self.assertEqual(ml.get("Hub.md"), 1)      # Spoke links to Hub

    def test_tag_distribution(self):
        dist = analytics.tag_distribution(self.tmp)
        self.assertEqual(dist["prayer"], 1)
        self.assertEqual(dist["prayers"], 1)

    def test_stale(self):
        old = Path(self.tmp) / "Old.md"
        old.write_text("old note", encoding="utf-8")
        past = time.time() - 200 * 86400
        os.utime(old, (past, past))
        self.assertIn("Old.md", analytics.stale_notes(self.tmp, days=180))
        self.assertNotIn("Hub.md", analytics.stale_notes(self.tmp, days=180))

    def test_tag_merge_suggestions(self):
        merges = analytics.suggest_tag_merges(self.tmp, embedder=_Embedder(), threshold=0.99)
        pairs = {frozenset((k, m)) for k, m, _ in merges}
        self.assertIn(frozenset(("prayer", "prayers")), pairs)

    def test_unsourced_notes(self):
        v = Path(self.tmp)
        (v / "Lonely.md").write_text("The secret order had exactly 4212 monks in 1450.", encoding="utf-8")
        (v / "Backed.md").write_text("Everest is 8848 metres tall.", encoding="utf-8")
        (v / "Support.md").write_text("Climbers note Everest reaches 8848 metres.", encoding="utf-8")
        uns = analytics.unsourced_notes(self.tmp)
        self.assertIn("Lonely.md", uns)        # no other note supports 4212/1450
        self.assertNotIn("Backed.md", uns)     # Support.md corroborates 8848

    def test_report_note_written(self):
        rel = analytics.write_report(self.tmp, embedder=_Embedder(), now=datetime(2026, 7, 8))
        self.assertTrue(rel.startswith("AI/Reports/vault-analytics-"))
        txt = (Path(self.tmp) / rel).read_text(encoding="utf-8")
        self.assertIn("Orphans", txt)
        self.assertIn("[[Lonely]]", txt)


if __name__ == "__main__":
    unittest.main()

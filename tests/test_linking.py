"""M36 (C4) — connective-tissue linking service: merge vector + graph, validate, feedback-filter."""

import tempfile
import unittest
from pathlib import Path

from assistant_core import linking, feedback


class _Rag:
    def __init__(self, hits):
        self._hits = hits
    def has_index(self):
        return True
    def relevant_notes(self, note_path, k=5):
        return self._hits


class _Graph:
    def __init__(self, neigh=(), tagn=()):
        self._n, self._t = set(neigh), set(tagn)
    def neighbors(self, note_path):
        return set(self._n)
    def tag_neighbors(self, note_path):
        return set(self._t)


class LinkingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        for n in ("Alpha", "Beta", "Gamma", "Note"):
            (v / f"{n}.md").write_text("x", encoding="utf-8")
        self._fb = feedback._FILE
        feedback._FILE = v / "feedback.json"

    def tearDown(self):
        feedback._FILE = self._fb

    def test_validates_against_vault(self):
        rag = _Rag([{"path": "Alpha.md", "score": 0.9}, {"path": "Ghost.md", "score": 0.8}])
        out = linking.related(self.tmp, "Note.md", rag=rag)
        self.assertIn("Alpha", out)
        self.assertNotIn("Ghost", out)          # not a real note → dropped

    def test_merges_vector_and_graph_scores(self):
        rag = _Graph  # noqa (unused placeholder to keep names explicit)
        r = _Rag([{"path": "Alpha.md", "score": 0.2}])
        g = _Graph(neigh={"Beta.md"}, tagn={"Alpha.md"})
        out = linking.related(self.tmp, "Note.md", rag=r, graph=g, k=5)
        # Alpha appears in BOTH signals (0.2 + 0.35) → outranks Beta (0.5)? 0.55 > 0.5
        self.assertEqual(out[0], "Alpha")
        self.assertIn("Beta", out)

    def test_excludes_self(self):
        r = _Rag([{"path": "Note.md", "score": 0.99}, {"path": "Alpha.md", "score": 0.5}])
        out = linking.related(self.tmp, "Note.md", rag=r)
        self.assertNotIn("Note", out)

    def test_feedback_suppresses_rejected_link(self):
        feedback.record("link", "Alpha", False, scope="Note.md")
        feedback.record("link", "Alpha", False, scope="Note.md")
        r = _Rag([{"path": "Alpha.md", "score": 0.9}, {"path": "Beta.md", "score": 0.5}])
        out = linking.related(self.tmp, "Note.md", rag=r)
        self.assertNotIn("Alpha", out)          # suppressed on this note
        self.assertIn("Beta", out)

    def test_empty_without_signals(self):
        self.assertEqual(linking.related(self.tmp, "Note.md"), [])


if __name__ == "__main__":
    unittest.main()

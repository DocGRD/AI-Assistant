"""M18 Slices 1-2 — entity/relation extraction + Markdown graph store. Stdlib unittest."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.graph.extractor import parse_triples, extract_triples
from assistant_core.graph import store as G


class ParseTriplesTests(unittest.TestCase):
    def test_parses_and_cleans(self):
        reply = ("Rocket Mass Heater | uses | Thermal Mass\n"
                 "Rocket Mass Heater | is a | Masonry Heater\n"
                 "garbage line without pipes\n"
                 "NONE")
        t = parse_triples(reply)
        self.assertIn(("Rocket Mass Heater", "uses", "Thermal Mass"), t)
        self.assertIn(("Rocket Mass Heater", "is a", "Masonry Heater"), t)
        self.assertEqual(len(t), 2)

    def test_none_and_self_loop(self):
        self.assertEqual(parse_triples("NONE"), [])
        self.assertEqual(parse_triples("X | equals | X"), [])   # self-loop dropped

    def test_rejects_numeric_and_fragment_entities(self):
        # Pure numbers / quantities must NOT become entities (they flooded the graph with junk).
        self.assertEqual(parse_triples("Solomon | offered | 100000"), [])
        self.assertEqual(parse_triples("reign | lasted | 16"), [])
        # …but legitimate digit-led names (a word is present) are kept.
        self.assertEqual(parse_triples("John | wrote | 1 John"), [("John", "wrote", "1 John")])

    def test_caps_at_twelve(self):
        reply = "\n".join(f"S{i} | rel | O{i}" for i in range(20))
        self.assertEqual(len(parse_triples(reply)), 12)


class ExtractTriplesTests(unittest.TestCase):
    def test_forces_private_single_call(self):
        calls = {"private": None, "n": 0}
        class _Router:
            config: dict = {}
            available_models: list = []
            def generate(self, messages, system_prompt="", private=False, **kw):
                calls["private"] = private; calls["n"] += 1
                return "Alpha | relates to | Beta", "groq"
        # Note text must clear the extractor's "skip trivially short notes" gate (>= 40 clean chars).
        t = extract_triples(_Router(), "Some note text long enough to warrant graph extraction here.")
        self.assertEqual(t, [("Alpha", "relates to", "Beta")])
        self.assertTrue(calls["private"])
        self.assertEqual(calls["n"], 1)

    def test_no_router_or_empty(self):
        self.assertEqual(extract_triples(None, "x"), [])
        class _R:
            def generate(self, **kw): return "", "groq"
        self.assertEqual(extract_triples(_R(), "  "), [])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_merge_creates_entities_and_is_idempotent(self):
        triples = [("Rocket Mass Heater", "uses", "Thermal Mass")]
        r1 = G.merge_triples(self.vault, triples, "06 - Projects/Heating.md")
        self.assertEqual(r1["entities"], 2)          # subject + object
        self.assertEqual(r1["relations"], 1)
        subj = Path(self.vault) / G.ENTITIES_DIR / "Rocket Mass Heater.md"
        self.assertTrue(subj.exists())
        body = subj.read_text(encoding="utf-8")
        self.assertIn("- uses [[Thermal Mass]]", body)
        self.assertIn("- [[Heating]]", body)         # source backlink
        # re-merge → no duplicate relation
        r2 = G.merge_triples(self.vault, triples, "06 - Projects/Heating.md")
        self.assertEqual(r2["relations"], 0)
        self.assertEqual(subj.read_text(encoding="utf-8").count("- uses [[Thermal Mass]]"), 1)

    def test_private_is_sticky(self):
        G.merge_triples(self.vault, [("A", "x", "B")], "n.md", private=True)
        data = G._load_entity(self.vault, "A")
        self.assertTrue(data["private"])
        # a later public merge does not downgrade
        G.merge_triples(self.vault, [("A", "y", "C")], "m.md", private=False)
        self.assertTrue(G._load_entity(self.vault, "A")["private"])

    def test_read_subgraph_bfs_depth(self):
        G.merge_triples(self.vault, [("A", "to", "B"), ("B", "to", "C")], "n.md")
        ids = {n["id"] for n in G.read_subgraph(self.vault, "A", depth=1)["nodes"]}
        self.assertIn("A", ids)
        self.assertIn("B", ids)                       # depth 1 neighbour
        self.assertNotIn("C", ids)                    # depth 2 — excluded

    def test_read_subgraph_hides_private_neighbour(self):
        G.merge_triples(self.vault, [("A", "uses", "Thermal")], "pub.md")        # A public
        G.merge_triples(self.vault, [("Thermal", "stores", "Heat")], "priv.md",  # Thermal → private
                        private=True)
        ids = {n["id"] for n in G.read_subgraph(self.vault, "A", depth=1)["nodes"]}
        self.assertIn("A", ids)
        self.assertNotIn("Thermal", ids)              # neighbour now private → hidden
        ids2 = {n["id"] for n in
                G.read_subgraph(self.vault, "A", depth=1, include_private=True)["nodes"]}
        self.assertIn("Thermal", ids2)

    def test_read_subgraph_unknown_node(self):
        self.assertEqual(G.read_subgraph(self.vault, "Nope", 1), {"nodes": [], "edges": []})

    def test_list_entities_by_degree_and_privacy(self):
        G.merge_triples(self.vault, [("Hub", "to", "A"), ("Hub", "to", "B")], "n.md")
        G.merge_triples(self.vault, [("Secret", "to", "X")], "p.md", private=True)
        ents = G.list_entities(self.vault)
        ids = [e["id"] for e in ents]
        self.assertEqual(ids[0], "Hub")                 # most-connected first
        self.assertNotIn("Secret", ids)                 # private hidden by default
        self.assertIn("Secret", [e["id"] for e in G.list_entities(self.vault, include_private=True)])


class _TripleRouter:
    # Mirror the real router's interface used by the extractor (config + available_models),
    # so graph extraction takes the normal cloud path instead of a provider override.
    config: dict = {}
    available_models: list = []
    def __init__(self, reply): self.reply = reply
    def generate(self, messages, system_prompt="", **kw): return self.reply, "groq"


class JobTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _note(self, rel, body, private=False):
        p = self.vault / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        fm = "---\nprivate: true\n---\n" if private else ""
        p.write_text(fm + body, encoding="utf-8")

    def test_build_for_note_merges(self):
        from assistant_core.graph.job import build_graph_for_note
        self._note("06 - Projects/Heat.md",
                   "A rocket heater uses thermal mass to store and radiate heat over many hours.")
        rep = build_graph_for_note(self.vault, _TripleRouter("Rocket Heater | uses | Thermal Mass"),
                                   "06 - Projects/Heat.md")
        self.assertEqual(rep["triples"], 1)
        self.assertTrue((self.vault / G.ENTITIES_DIR / "Rocket Heater.md").exists())

    def test_incremental_skips_unchanged_and_derived(self):
        from assistant_core.graph.job import build_graph
        self._note("06 - Projects/Heat.md", "Rocket heater note.")
        self._note("AI/System/Provider-Registry.md", "should be skipped")   # derived tree
        router = _TripleRouter("A | rel | B")
        r1 = build_graph(self.vault, router, limit=50)
        self.assertIn("06 - Projects/Heat.md", r1["processed"])
        self.assertNotIn("AI/System/Provider-Registry.md", r1["processed"])  # skipped
        r2 = build_graph(self.vault, router, limit=50)                       # unchanged → no work
        self.assertEqual(r2["processed"], [])

    def test_private_note_marks_private_entities(self):
        from assistant_core.graph.job import build_graph_for_note
        self._note("Journal.md",
                   "The Secret Plan involves a hidden Bunker stocked for the long winter ahead.",
                   private=True)
        build_graph_for_note(self.vault, _TripleRouter("Secret Plan | involves | Bunker"), "Journal.md")
        self.assertTrue(G._load_entity(self.vault, "Secret Plan")["private"])


class AliasMergeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_suggest_aliases_substring(self):
        G.merge_triples(self.vault, [("Thermal Mass", "x", "Y")], "n.md")
        G.merge_triples(self.vault, [("Thermal Masses", "x", "Z")], "m.md")
        pairs = [(c, a) for c, a, s in G.suggest_aliases(self.vault)]
        self.assertIn(("Thermal Masses", "Thermal Mass"), pairs)   # longer = canonical

    def test_merge_entities_unions_and_repoints(self):
        G.merge_triples(self.vault, [("Rocket Mass Heater", "uses", "Thermal Mass")], "n.md")
        G.merge_triples(self.vault, [("RMH", "is", "Efficient")], "m.md")
        G.merge_triples(self.vault, [("Cabin", "has", "RMH")], "c.md")   # incoming link to RMH
        self.assertTrue(G.merge_entities(self.vault, "Rocket Mass Heater", "RMH"))
        self.assertFalse((Path(self.vault) / G.ENTITIES_DIR / "RMH.md").exists())   # alias removed
        canon = G._load_entity(self.vault, "Rocket Mass Heater")
        self.assertIn(("is", "Efficient"), canon["relations"])          # unioned
        self.assertIn("RMH", canon["aliases"])                          # alias recorded
        self.assertIn(("has", "Rocket Mass Heater"),                    # incoming link repointed
                      G._load_entity(self.vault, "Cabin")["relations"])

    def test_merge_identical_is_noop(self):
        G.merge_triples(self.vault, [("A", "x", "B")], "n.md")
        self.assertFalse(G.merge_entities(self.vault, "A", "A"))


class GuideTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_find_entity_exact_substring_none(self):
        from assistant_core.graph.guide import find_entity
        G.merge_triples(self.vault, [("Rocket Mass Heater", "uses", "Thermal Mass")], "n.md")
        self.assertEqual(find_entity(self.vault, "Rocket Mass Heater"), "Rocket Mass Heater")
        self.assertEqual(find_entity(self.vault, "thermal mass"), "Thermal Mass")   # case/substring
        self.assertIsNone(find_entity(self.vault, "Penguins"))

    def test_build_guide_assembles_cited_answer(self):
        from assistant_core.graph.guide import build_guide
        (self.vault / "06 - Projects").mkdir(parents=True, exist_ok=True)
        (self.vault / "06 - Projects" / "Heat.md").write_text(
            "Rocket mass heaters store heat in thermal mass.", encoding="utf-8")
        G.merge_triples(self.vault, [("Rocket Mass Heater", "uses", "Thermal Mass")],
                        "06 - Projects/Heat.md")
        class _R:
            def generate(self, messages, system_prompt="", **kw):
                return "Rocket Mass Heater uses [[Thermal Mass]]. Related: Thermal Mass.", "groq"
        rep = build_guide(self.vault, _R(), "Rocket Mass Heater")
        self.assertIsNone(rep["error"])
        self.assertEqual(rep["entity"], "Rocket Mass Heater")
        self.assertIn("uses [[Thermal Mass]]", rep["guide"])
        self.assertIn("Heat", rep["sources"])

    def test_build_guide_no_entity(self):
        from assistant_core.graph.guide import build_guide
        rep = build_guide(self.vault, None, "Nothing Here")
        self.assertIn("no graph entity", rep["error"])

    def test_build_guide_respects_include_private(self):
        from assistant_core.graph.guide import build_guide
        (self.vault / "n.md").write_text("secret note", encoding="utf-8")
        G.merge_triples(self.vault, [("Alpha", "to", "Beta")], "n.md", private=True)  # both private
        class _R:
            def generate(self, messages, system_prompt="", **kw): return "guide", "groq"
        off = build_guide(self.vault, _R(), "Alpha", include_private=False)
        on  = build_guide(self.vault, _R(), "Alpha", include_private=True)
        self.assertEqual(off["sources"], [])          # private hidden by default
        self.assertIn("n", on["sources"])             # included when the setting is on


if __name__ == "__main__":
    unittest.main()

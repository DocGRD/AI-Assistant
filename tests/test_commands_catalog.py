"""M41 — Obsidian command-palette catalog: sync, search, resolve, propose-to-run."""

import importlib
import tempfile
import unittest
from pathlib import Path


class TestCommandsCatalog(unittest.TestCase):
    def setUp(self):
        # Point the module's state file at a throwaway temp path so tests never touch
        # the real state/commands.json, and reload to reset module-level state.
        import assistant_core.commands_catalog as cc
        self.cc = importlib.reload(cc)
        self._tmp = Path(tempfile.mkdtemp()) / "commands.json"
        self.cc._STATE_PATH = self._tmp

        self.sample = [
            {"id": "editor:toggle-bold", "name": "Toggle bold", "source": "core"},
            {"id": "daily-notes", "name": "Open today's daily note", "source": "core"},
            {"id": "templater-obsidian:insert-templater", "name": "Templater: Insert template",
             "source": "templater-obsidian"},
            {"id": "obsidian-excalidraw-plugin:excalidraw-autocreate",
             "name": "Excalidraw: Create new drawing", "source": "obsidian-excalidraw-plugin"},
            {"id": "app:delete-file", "name": "Delete current file", "source": "core"},
        ]

    # ── storage ────────────────────────────────────────────────────────────
    def test_replace_stores_and_dedups(self):
        n = self.cc.replace(self.sample + [self.sample[0]], plugins=["Templater", "Excalidraw"],
                            hash_="abc")
        self.assertEqual(n, 5)                          # duplicate id dropped
        self.assertEqual(self.cc.count(), 5)
        self.assertEqual(self.cc.current_hash(), "abc")
        self.assertIn("Templater", self.cc.plugin_sources())

    def test_self_plugin_is_filtered(self):
        self.cc.replace(self.sample + [
            {"id": "loremaster:open-chat", "name": "Open chat", "source": "loremaster"},
        ], plugins=["loremaster", "Templater"])
        ids = [c["id"] for c in self.cc.all_commands()]
        self.assertNotIn("loremaster:open-chat", ids)
        self.assertNotIn("loremaster", self.cc.plugin_sources())

    # ── search / resolve ─────────────────────────────────────────────────────
    def test_search_ranks_by_relevance(self):
        self.cc.replace(self.sample)
        hits = self.cc.search("template")
        self.assertTrue(hits)
        self.assertEqual(hits[0]["id"], "templater-obsidian:insert-templater")

    def test_search_multiword(self):
        self.cc.replace(self.sample)
        hits = self.cc.search("daily note")
        self.assertEqual(hits[0]["id"], "daily-notes")

    def test_resolve_by_id_and_name(self):
        self.cc.replace(self.sample)
        self.assertEqual(self.cc.resolve("daily-notes")["id"], "daily-notes")
        self.assertEqual(self.cc.resolve("Toggle bold")["id"], "editor:toggle-bold")
        self.assertEqual(self.cc.resolve("insert template")["id"],
                         "templater-obsidian:insert-templater")   # fuzzy fallback
        self.assertIsNone(self.cc.resolve("no such command xyzzy nope"))

    # ── risk flag ─────────────────────────────────────────────────────────────
    def test_risky_detection(self):
        self.assertTrue(self.cc.is_risky("app:delete-file", "Delete current file"))
        self.assertTrue(self.cc.is_risky("some:publish-note", "Publish"))
        self.assertFalse(self.cc.is_risky("editor:toggle-bold", "Toggle bold"))

    # ── proposal building ─────────────────────────────────────────────────────
    def test_make_proposal(self):
        self.cc.replace(self.sample)
        p = self.cc.make_proposal("templater-obsidian:insert-templater")
        self.assertEqual(p["kind"], "command_run")
        self.assertEqual(p["command_id"], "templater-obsidian:insert-templater")
        self.assertFalse(p["risky"])
        risky = self.cc.make_proposal("Delete current file")     # resolves by name
        self.assertEqual(risky["command_id"], "app:delete-file")
        self.assertTrue(risky["risky"])
        self.assertIsNone(self.cc.make_proposal("does-not-exist-abc"))

    # ── unified handler ────────────────────────────────────────────────────────
    def test_handle_search_and_list(self):
        self.cc.replace(self.sample, plugins=["Templater"])
        res = self.cc.handle("command:search", "bold")
        self.assertIn("Toggle bold", res["output"])
        self.assertIsNone(res["proposal"])
        res = self.cc.handle("command:list", "")
        self.assertIn("Templater", res["output"])

    def test_handle_run_returns_proposal(self):
        self.cc.replace(self.sample)
        res = self.cc.handle("command:run", "daily-notes")
        self.assertIsNotNone(res["proposal"])
        self.assertEqual(res["proposal"]["command_id"], "daily-notes")

    def test_handle_run_nonexact_offers_candidates(self):
        # A partial that isn't an exact id/name must NOT auto-run — it offers candidates.
        self.cc.replace(self.sample)
        res = self.cc.handle("command:run", "template")
        self.assertIsNone(res["proposal"])
        self.assertIn("Closest matches", res["output"])
        self.assertIn("templater-obsidian:insert-templater", res["output"])

    def test_summary_mentions_count_and_plugins(self):
        self.cc.replace(self.sample, plugins=["Templater", "Excalidraw"])
        s = self.cc.summary()
        self.assertIn("5", s)
        self.assertIn("Templater", s)
        self.assertIn("command:search", s)

    def test_summary_empty_when_no_catalog(self):
        self.assertEqual(self.cc.summary(), "")


if __name__ == "__main__":
    unittest.main()

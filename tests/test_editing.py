"""
Tests for Milestone 9 Slice 4 — shared editing helpers + watcher edit staging.

Stdlib unittest. No network: a fake router returns a fixed replacement.

Run with:
    python -m unittest tests.test_editing -v
"""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from assistant_core import editing
from assistant_core.watcher.frontmatter_parser import FrontmatterParser
from assistant_core.watcher.request_handler import RequestHandler


class EditingHelpersTests(unittest.TestCase):

    def test_clean_and_parse(self):
        self.assertEqual(editing.clean_edit_reply("```\nhello\n```"), "hello")
        self.assertEqual(editing.parse_options("1. a\n- b\n\"a\"\nc"), ["a", "b", "c"])

    def test_section_text_found_and_missing(self):
        body = "# Title\n\nintro\n\n## Notes\n\nline one\nline two\n\n## Other\n\nx\n"
        text, found = editing.section_text(body, "Notes")
        self.assertTrue(found)
        self.assertEqual(text, "line one\nline two")
        self.assertEqual(editing.section_text(body, "Missing"), ("", False))
        # heading reference may include leading '#'
        self.assertTrue(editing.section_text(body, "## Notes")[1])

    def test_split_for_edit_small_is_single_chunk(self):
        self.assertEqual(editing.split_for_edit("short text", 3500), ["short text"])

    def test_split_for_edit_chunks_large_text_in_order(self):
        paras = [f"Paragraph number {i} " + ("x" * 300) for i in range(10)]
        text = "\n\n".join(paras)
        chunks = editing.split_for_edit(text, max_chars=800)
        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), 800)
        # order preserved: every paragraph appears, in sequence, across the chunks
        joined = "\n\n".join(chunks)
        self.assertEqual([p.split()[2] for p in text.split("\n\n")],
                         [str(i) for i in range(10)])
        for i in range(10):
            self.assertIn(f"Paragraph number {i} ", joined)

    def test_split_for_edit_hard_splits_one_huge_paragraph(self):
        chunks = editing.split_for_edit("y" * 5000, max_chars=1000)
        self.assertEqual(len(chunks), 5)
        self.assertEqual("".join(chunks), "y" * 5000)

    def test_proposal_block_roundtrip(self):
        prop = editing.make_proposal(
            note_path="n.md", scope="section", intent="tighten",
            original_text="line one\nline two", replacement="tight",
            anchor=editing.make_anchor("Notes", "line one\nline two", "## Notes\nline one\nline two"),
            source="vault", provider="groq",
        )
        block = editing.render_proposal_block(prop)
        self.assertIn(editing.BEGIN_MARK, block)
        parsed = editing.extract_proposal("BODY\n" + block)
        self.assertEqual(parsed["scope"], "section")
        self.assertEqual(parsed["replacement"], "tight")
        self.assertEqual(parsed["anchor"]["heading"], "Notes")
        # stripping removes the whole proposal section
        self.assertNotIn(editing.BEGIN_MARK, editing.strip_proposal_block("BODY\n" + block))


class _FakeRouter:
    def __init__(self, reply="REVISED SECTION"):
        self._reply = reply
        self.captured_private = None

    def generate(self, messages, system_prompt="", private=False, allow_webui=True, **kw):
        self.captured_private = private
        return self._reply, "groq"


class WatcherStagingTests(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.vault = Path(self._tmp.name)
        self.router = _FakeRouter()
        self.handler = RequestHandler(vault_path=str(self.vault), router=self.router,
                                      registry=None, system_prompt="SYS")

    def tearDown(self):
        self._tmp.cleanup()

    def _write_note(self, name, fm_lines, body):
        p = self.vault / name
        p.write_text("---\n" + "\n".join(fm_lines) + "\n---\n\n" + body, encoding="utf-8")
        return p

    def test_section_edit_stages_proposal_without_touching_body(self):
        p = self._write_note(
            "edit.md",
            ['assistant-status: pending', 'assistant-request: "tighten this"',
             'assistant-edit: true', 'assistant-edit-scope: section', 'assistant-edit-target: Notes'],
            "# Title\n\n## Notes\n\noriginal line one\noriginal line two\n\n## Other\n\nkeep me\n",
        )
        ok = self.handler.process("edit.md", "tighten this")
        self.assertFalse(ok)   # proposal-pending, not 'done'

        content = p.read_text(encoding="utf-8")
        fm, body = FrontmatterParser.extract(content)
        self.assertEqual(fm.get("assistant-status"), "proposal-pending")

        before_block = content.split(editing.PROPOSAL_HEADING)[0]
        self.assertIn("original line one", before_block)        # body preserved
        self.assertNotIn("REVISED SECTION", before_block)        # replacement NOT written to body

        prop = editing.extract_proposal(content)
        self.assertIsNotNone(prop)
        self.assertEqual(prop["scope"], "section")
        self.assertEqual(prop["original_text"], "original line one\noriginal line two")
        self.assertEqual(prop["replacement"], "REVISED SECTION")
        self.assertEqual(prop["anchor"]["heading"], "Notes")

    def test_bad_heading_writes_error_not_proposal(self):
        p = self._write_note(
            "bad.md",
            ['assistant-status: pending', 'assistant-request: "x"',
             'assistant-edit: true', 'assistant-edit-scope: section', 'assistant-edit-target: Nope'],
            "## Notes\n\nstuff\n",
        )
        self.handler.process("bad.md", "x")
        content = p.read_text(encoding="utf-8")
        fm, _ = FrontmatterParser.extract(content)
        self.assertEqual(fm.get("assistant-status"), "error")
        self.assertNotIn(editing.BEGIN_MARK, content)

    def test_staged_proposal_is_committable(self):
        # Stage, then simulate the plugin commit (strip block, exact-match resolve,
        # replace, clear status) to prove the contract round-trips.
        p = self._write_note(
            "rt.md",
            ['assistant-status: pending', 'assistant-request: "tighten"',
             'assistant-edit: true', 'assistant-edit-scope: section', 'assistant-edit-target: Notes'],
            "# T\n\n## Notes\n\nkeep alpha\nkeep beta\n\n## After\n\ntail\n",
        )
        self.handler.process("rt.md", "tighten")
        content = p.read_text(encoding="utf-8")
        prop = editing.extract_proposal(content)

        cleaned = editing.strip_proposal_block(content)
        self.assertNotIn(editing.BEGIN_MARK, cleaned)
        # the plugin resolves by exact match of original_text — it must be present
        self.assertIn(prop["original_text"], cleaned)
        committed = cleaned.replace(prop["original_text"], prop["replacement"], 1)
        self.assertIn("REVISED SECTION", committed)   # region replaced
        self.assertIn("## Notes", committed)           # heading preserved
        self.assertIn("tail", committed)               # rest of note intact

    def test_private_note_threads_private(self):
        self._write_note(
            "priv.md",
            ['assistant-status: pending', 'assistant-request: "x"', 'private: true',
             'assistant-edit: true', 'assistant-edit-scope: whole-note'],
            "some prose to revise\n",
        )
        self.handler.process("priv.md", "x")
        self.assertTrue(self.router.captured_private)   # privacy threaded into generate


if __name__ == "__main__":
    unittest.main()

"""M30 — dangling-[[link]] neutralisation + write-tool integration."""

import tempfile
import unittest
from pathlib import Path

from assistant_core.links import neutralize_dangling, link_exists, link_targets
from assistant_core.tools.create_note import CreateNoteTool
from assistant_core.tools.update_note import UpdateNoteTool


class NeutralizeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        (v / "Real Note.md").write_text("hi", encoding="utf-8")
        (v / "folder").mkdir()
        (v / "folder" / "Deep.md").write_text("deep", encoding="utf-8")

    def test_valid_links_untouched(self):
        text = "See [[Real Note]] and [[folder/Deep]] and [[Real Note|the real one]]."
        out, removed = neutralize_dangling(text, self.tmp)
        self.assertEqual(out, text)
        self.assertEqual(removed, [])

    def test_dangling_stripped_to_plain_text(self):
        text = "Refs [[Ghost Note]] and [[Real Note]] and [[Nowhere|that thing]]."
        out, removed = neutralize_dangling(text, self.tmp, "strip")
        self.assertNotIn("[[Ghost Note]]", out)
        self.assertNotIn("[[Nowhere", out)
        self.assertIn("Ghost Note", out)          # kept as plain text
        self.assertIn("that thing", out)          # alias used as display text
        self.assertIn("[[Real Note]]", out)       # valid link preserved
        self.assertEqual(set(removed), {"Ghost Note", "Nowhere"})

    def test_flag_policy_keeps_link_with_marker(self):
        out, removed = neutralize_dangling("[[Ghost]]", self.tmp, "flag")
        self.assertIn("[[Ghost]] ⚠", out)
        self.assertEqual(removed, ["Ghost"])

    def test_off_policy_no_change(self):
        text = "[[Ghost]]"
        out, removed = neutralize_dangling(text, self.tmp, "off")
        self.assertEqual(out, text)
        self.assertEqual(removed, [])

    def test_embeds_are_left_alone(self):
        text = "![[some-image.png]] and [[Ghost]]"
        out, _ = neutralize_dangling(text, self.tmp, "strip")
        self.assertIn("![[some-image.png]]", out)   # embed preserved

    def test_link_exists_and_targets(self):
        self.assertTrue(link_exists("Real Note", self.tmp))
        self.assertFalse(link_exists("Ghost Note", self.tmp))
        self.assertEqual(link_targets("[[A]] [[A]] [[B|x]]"), ["A", "B"])


class WriteToolIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        (Path(self.tmp) / "Existing.md").write_text("x", encoding="utf-8")

    def test_create_note_strips_and_footnotes(self):
        tool = CreateNoteTool(self.tmp)   # default policy = strip
        res = tool.run("New.md\nLinks to [[Existing]] and [[Fake One]].")
        self.assertTrue(res.success)
        body = (Path(self.tmp) / "New.md").read_text(encoding="utf-8")
        self.assertIn("[[Existing]]", body)
        self.assertNotIn("[[Fake One]]", body)
        self.assertIn("Removed unresolved links: Fake One", body)
        self.assertEqual(res.metadata["removed_links"], ["Fake One"])

    def test_create_note_off_policy_keeps_fakes(self):
        tool = CreateNoteTool(self.tmp, {"link_validation": "off"})
        res = tool.run("New2.md\nLinks to [[Fake]].")
        self.assertTrue(res.success)
        self.assertIn("[[Fake]]", (Path(self.tmp) / "New2.md").read_text(encoding="utf-8"))

    def test_update_note_strips_on_append(self):
        tool = UpdateNoteTool(self.tmp)
        res = tool.run("Existing.md\nMore about [[Ghost]].")
        self.assertTrue(res.success)
        body = (Path(self.tmp) / "Existing.md").read_text(encoding="utf-8")
        self.assertNotIn("[[Ghost]]", body)
        self.assertIn("Removed unresolved links: Ghost", body)


if __name__ == "__main__":
    unittest.main()

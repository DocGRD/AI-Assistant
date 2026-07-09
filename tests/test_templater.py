"""M40 — typed/templated note fill (best-effort; integrates with Templater/Templates)."""

import json
import tempfile
import unittest
from pathlib import Path

from assistant_core import templater


class _Router:
    available_providers = ["groq"]
    def generate(self, messages, task=None, private=False, allow_webui=True, **kw):
        return "Attendees: Alice, Bob\nTopic: Q3 planning", "groq"


class TemplaterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        v = Path(self.tmp)
        # simulate Templater config pointing at a Templates folder
        cfg = v / ".obsidian" / "plugins" / "templater-obsidian"
        cfg.mkdir(parents=True, exist_ok=True)
        (cfg / "data.json").write_text(json.dumps({"templates_folder": "Templates"}), encoding="utf-8")
        (v / "Templates").mkdir()
        (v / "Templates" / "Meeting.md").write_text(
            "# Meeting <% tp.date.now() %>\n\nAttendees: {{Attendees}}\nTopic: {{Topic}}\n"
            "<!-- fill: one-line agenda -->\n", encoding="utf-8")

    def test_detects_templates(self):
        self.assertEqual(templater.templates_folder(self.tmp), "Templates")
        self.assertIn("Meeting", templater.list_templates(self.tmp))

    def test_fill_keeps_templater_tags_fills_markers(self):
        rep = templater.fill_template(self.tmp, "Meeting", "Meeting about Q3 planning with Alice and Bob",
                                      router=_Router())
        self.assertTrue(rep["ok"])
        out = (Path(self.tmp) / rep["path"]).read_text(encoding="utf-8")
        self.assertIn("<% tp.date.now() %>", out)        # Templater tag untouched
        self.assertIn("Alice, Bob", out)                 # {{Attendees}} filled
        self.assertNotIn("{{Attendees}}", out)
        self.assertTrue(rep["path"].startswith("AI/Proposed/template-"))

    def test_missing_template(self):
        rep = templater.fill_template(self.tmp, "Nope", "x", router=_Router())
        self.assertFalse(rep["ok"])

    def test_no_router_leaves_placeholders(self):
        rep = templater.fill_template(self.tmp, "Meeting", "ctx", router=None)
        self.assertTrue(rep["ok"])
        out = (Path(self.tmp) / rep["path"]).read_text(encoding="utf-8")
        self.assertIn("(Attendees)", out)                # visible placeholder, not left as {{...}}


if __name__ == "__main__":
    unittest.main()

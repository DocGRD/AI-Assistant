"""M37 — trust on write: flag/source factual claims the vault can't support."""

import tempfile
import unittest
from pathlib import Path

from assistant_core import write_guard


class WriteGuardTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        # a note that DOES support one claim
        (Path(self.tmp) / "Everest.md").write_text(
            "Mount Everest rises to 8848 metres above sea level.", encoding="utf-8")

    def test_off_is_noop(self):
        out, st = write_guard.guard_content(self.tmp, "K2 is 8611 m tall.", {"write_guard": "off"})
        self.assertEqual(st, "off")
        self.assertNotIn("Unsourced", out)

    def test_prose_without_quantities_is_clean(self):
        text = "I think prayer is important and worth doing every morning."
        out, st = write_guard.guard_content(self.tmp, text, {"write_guard": "flag"})
        self.assertEqual(st, "clean")
        self.assertEqual(out, text)

    def test_unsourced_quantity_is_flagged(self):
        text = "The obscure village of Zzyx had exactly 4212 residents in the census."
        out, st = write_guard.guard_content(self.tmp, text, {"write_guard": "flag"})
        self.assertEqual(st, "flagged")
        self.assertIn("Unsourced claims", out)
        self.assertIn("4212", out)

    def test_supported_claim_not_flagged(self):
        text = "Everest reaches 8848 metres."
        out, st = write_guard.guard_content(self.tmp, text, {"write_guard": "flag"})
        self.assertEqual(st, "clean")

    def test_source_policy_cites_supporting_notes(self):
        text = "Everest reaches 8848 metres."
        out, st = write_guard.guard_content(self.tmp, text, {"write_guard": "source"})
        self.assertIn("**Sources:**", out)
        self.assertIn("[[Everest]]", out)

    def test_never_raises_on_bad_vault(self):
        out, st = write_guard.guard_content(None, "3000 things", {"write_guard": "flag"})
        self.assertEqual(st, "off")


if __name__ == "__main__":
    unittest.main()

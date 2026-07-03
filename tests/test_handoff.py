"""
M7 / M8 — web handoff + three-prompt separation + headless default.

- The WebUI partner prompt carries NO vault: command syntax (M8 three-prompt rule).
- The handoff-return loop converts plain-English suggestions into vault: commands (M7).
- Headless is the default; --terminal forces the chat loop (M8). Stdlib unittest.
"""

import tempfile
import unittest
import sys

from assistant_core.providers.webui_provider import WebUIProvider, DEFAULT_WEBUI_PROMPT
from assistant_core.providers.base_provider import Message, ProviderWebUIHandoff
from assistant_core.server.suggestions import extract_vault_suggestions


class WebUIPromptTests(unittest.TestCase):
    def test_default_prompt_has_no_vault_command_syntax(self):        # M8
        self.assertNotIn("vault:", DEFAULT_WEBUI_PROMPT.lower())

    def test_packaged_handoff_has_no_vault_syntax_and_carries_question(self):  # M7/M8
        with tempfile.TemporaryDirectory() as d:
            provider = WebUIProvider({"vault_path": d})       # no WebUI-Prompt.md → default
            try:
                provider.generate([Message(role="user", content="explain rocket stoves")])
                self.fail("WebUIProvider.generate should raise ProviderWebUIHandoff")
            except ProviderWebUIHandoff as handoff:
                pkg = handoff.packaged_prompt
                self.assertNotIn("vault:", pkg.lower())
                self.assertIn("rocket stoves", pkg)


class SuggestionExtractionTests(unittest.TestCase):
    def test_extracts_search_suggestion(self):                # M7 — research loop
        cmds = extract_vault_suggestions("You may want to search your vault for rocket stove dimensions.")
        self.assertIn("vault:search rocket stove dimensions", cmds)

    def test_plain_text_yields_no_commands(self):
        self.assertEqual(extract_vault_suggestions("Just a normal answer with no hints."), [])


class HeadlessTests(unittest.TestCase):
    def _headless(self, extra_argv):
        from assistant_core.app import _is_headless
        old = sys.argv
        try:
            sys.argv = ["assistant"] + extra_argv
            return _is_headless()
        finally:
            sys.argv = old

    def test_terminal_flag_forces_interactive(self):          # M8
        self.assertFalse(self._headless(["--terminal"]))

    def test_headless_flag_forces_headless(self):
        self.assertTrue(self._headless(["--headless"]))


if __name__ == "__main__":
    unittest.main()

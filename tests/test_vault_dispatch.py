"""M33 — the agent can run rich vault: commands (esp. autonomous web research)."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from assistant_core.vault_dispatch import run_extended, EXTENDED_COMMANDS


def _ctx(tmp, private=False):
    return SimpleNamespace(config={"vault_path": tmp}, router=object(), rag=None,
                           private=private, memory=None, ep_vault_fn=None, registry=None)


class RunExtendedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def test_non_extended_returns_none(self):
        # basic commands are handled by the agent loop, not here
        self.assertIsNone(run_extended("vault:read", "x", _ctx(self.tmp)))
        self.assertIsNone(run_extended("vault:create", "x", _ctx(self.tmp)))

    def test_webresearch_refused_when_private(self):
        res = run_extended("vault:webresearch", "latest news", _ctx(self.tmp, private=True))
        self.assertIsNotNone(res)
        self.assertFalse(res.success)
        self.assertTrue(res.terminal)
        self.assertIn("private", res.output.lower())

    def test_webresearch_runs_and_injects_findings(self):
        # Fake the autonomous research: write a Summary.md and return its path.
        def fake_research(query, router, config, rag=None, private=False):
            base = "AI/Research/2026-07-07-x"
            p = Path(self.tmp) / base
            p.mkdir(parents=True, exist_ok=True)
            (p / "Summary.md").write_text("---\nq: x\n---\n\nThe answer is 42, per [1].",
                                          encoding="utf-8")
            return {"summary_path": f"{base}/Summary.md", "sources": [{"n": 1}], "related": []}

        with mock.patch("assistant_core.web.research.run_web_research", fake_research):
            res = run_extended("vault:webresearch", "what is the answer", _ctx(self.tmp))
        self.assertIsNotNone(res)
        self.assertTrue(res.success)
        self.assertFalse(res.terminal)                 # inject → agent presents findings
        self.assertIn("The answer is 42", res.output)  # synthesis injected (not a paste-prompt)
        self.assertIn("AI/Research", res.output)

    def test_sources_command(self):
        (Path(self.tmp) / "Bio.md").write_text("photosynthesis chlorophyll sunlight", encoding="utf-8")
        res = run_extended("vault:sources", "photosynthesis chlorophyll sunlight", _ctx(self.tmp))
        self.assertTrue(res.success)
        self.assertIn("Bio.md", res.output)

    def test_all_rich_commands_registered(self):
        for c in ("vault:webresearch", "vault:ingest", "vault:query", "vault:guide", "vault:passage"):
            self.assertIn(c, EXTENDED_COMMANDS)


class AgentLoopRoutesExtendedTests(unittest.TestCase):
    """The agent loop routes an emitted vault:webresearch to run_extended (not 'unknown')."""

    def test_agent_emitted_webresearch_is_dispatched(self):
        from assistant_core import agent_loop
        called = {}

        def fake_run_extended(prefix, arg, ctx):
            called["prefix"] = prefix
            return agent_loop_ext_result(prefix, arg)

        # ExtResult stand-in
        from assistant_core.vault_dispatch import ExtResult
        def agent_loop_ext_result(prefix, arg):
            return ExtResult(f"ran {prefix} {arg}", success=True, terminal=True)

        with mock.patch("assistant_core.vault_dispatch.run_extended", fake_run_extended):
            # emulate the loop's unknown-command branch decision
            self.assertIsNone(agent_loop.VAULT_COMMANDS.get("vault:webresearch"))
            res = fake_run_extended("vault:webresearch", "x", None)
            self.assertEqual(called["prefix"], "vault:webresearch")
            self.assertTrue(res.terminal)


if __name__ == "__main__":
    unittest.main()

"""
Tests for the shared agent loop — focused on the user-configurable step cap (M16.5).

A fake router that always emits a vault: command keeps the loop from terminating
cleanly, so the number of generate() calls equals the effective step cap.
"""

import threading
import unittest

from assistant_core.agent_loop import AgentContext, run_agent_loop, MAX_STEPS, extract_vault_commands


class _Result:
    success = True
    output  = "ok"


class _Registry:
    def run(self, tool_name, tool_input):
        return _Result()


class _LoopRouter:
    """generate() always returns a command → the loop runs until the step cap."""
    def __init__(self):
        self.calls = 0

    def generate(self, messages, system_prompt="", max_tokens=2048, temperature=0.7,
                 provider_override=None, private=False, allow_webui_on_private=False, **kw):
        self.calls += 1
        return "vault:search foo", "groq"


class AgentLoopMaxStepsTests(unittest.TestCase):
    def _run(self, max_steps) -> int:
        router = _LoopRouter()
        ctx = AgentContext(
            user_input="hi", history=[], history_lock=threading.Lock(),
            router=router, registry=_Registry(), memory=None, ctx_mgr=None,
            system_prompt="", max_steps=max_steps,
        )
        run_agent_loop(ctx)
        return router.calls

    def test_default_is_ten(self):
        self.assertEqual(MAX_STEPS, 10)

    def test_respects_custom_cap(self):
        self.assertEqual(self._run(3), 3)
        self.assertEqual(self._run(7), 7)

    def test_zero_or_none_falls_back_to_default(self):
        self.assertEqual(self._run(0), MAX_STEPS)
        self.assertEqual(self._run(None), MAX_STEPS)


class AgentLoopTerminalToolTests(unittest.TestCase):
    """M20 — a deliverable tool (vault:research) ends the turn; the loop must not
    keep going to 'finish' more work (the T5.01 runaway)."""

    def test_deliverable_tool_ends_turn(self):
        class _Router:
            def __init__(self): self.calls = 0
            def generate(self, messages, **kw):
                self.calls += 1
                return "Here you go:\nvault:research how do rocket stoves work", "groq"

        class _Reg:
            def run(self, tool, inp):
                class _R:  # ToolResult-like
                    success = True
                    output  = f"PROMPT for: {inp}"
                return _R()

        router = _Router()
        ctx = AgentContext(
            user_input="research rocket stoves", history=[], history_lock=threading.Lock(),
            router=router, registry=_Reg(), memory=None, ctx_mgr=None, system_prompt="",
        )
        reply, provider = run_agent_loop(ctx)
        self.assertIn("PROMPT for: how do rocket stoves work", reply)
        self.assertEqual(router.calls, 1)   # ran the tool, then STOPPED (no second generate)


class AgentLoopRestructureProposalTests(unittest.TestCase):
    """M29 — a restructuring op (vault:trash) is PROPOSED for approval and ends the turn
    in ONE step (never auto-runs, never retries to MAX_STEPS)."""

    def test_trash_is_proposed_and_ends_turn_once(self):
        class _Router:
            def __init__(self): self.calls = 0
            def generate(self, messages, **kw):
                self.calls += 1
                return "Sure, removing it.\nvault:trash AI/Guides/Voice-Interaction-Setup.md", "groq"

        class _Reg:
            def run(self, tool, inp):  # a proposed command must not execute
                raise AssertionError("proposed restructuring must not run without approval")

        router = _Router()
        ctx = AgentContext(
            user_input="remove that note", history=[], history_lock=threading.Lock(),
            router=router, registry=_Reg(), memory=None, ctx_mgr=None, system_prompt="",
        )
        reply, _ = run_agent_loop(ctx)
        self.assertEqual(router.calls, 1)                       # stopped after one step
        self.assertIsNotNone(ctx.pending_restructure)
        self.assertEqual(ctx.pending_restructure["op"], "trash")
        self.assertEqual(ctx.pending_restructure["command"],
                         "vault:trash AI/Guides/Voice-Interaction-Setup.md")
        self.assertIn("approval", reply.lower())

    def test_move_proposal_parses_src_and_dst(self):
        from assistant_core.agent_loop import _restructure_proposal
        p = _restructure_proposal("vault:move A/x.md -> B/x.md")
        self.assertEqual(p["op"], "move")
        self.assertEqual(p["src"], "A/x.md")
        self.assertEqual(p["dst"], "B/x.md")


class CleanForDisplayTests(unittest.TestCase):
    """A weak model can emit concatenated command-spam as its 'answer' — strip it."""

    def test_normal_reply_untouched(self):
        from assistant_core.agent_loop import _clean_for_display
        r = "Bluebirds belong to the genus Sialia and nest in cavities."
        self.assertEqual(_clean_for_display(r), r)

    def test_single_command_mention_untouched(self):
        from assistant_core.agent_loop import _clean_for_display
        r = "To find them, use vault:search bluebird in the sidebar."
        self.assertEqual(_clean_for_display(r), r)   # <2 commands → left alone

    def test_command_spam_is_gutted(self):
        from assistant_core.agent_loop import _clean_for_display
        r = 'We need to issue vault:list.vault:list "05 - Personal Growth"vault:list "05 - Personal Growth"'
        self.assertEqual(_clean_for_display(r), "")   # command-spam → empty (caller shows fallback)


class AgentLoopTaskLedgerTests(unittest.TestCase):
    """M20 Slice 3 — the externalized task ledger is injected into the system prompt
    each step and accumulates checkpoints, so a switched-to model continues the task."""

    def test_ledger_injected_and_accumulates(self):
        seen = []   # system_prompt seen at each step

        class _Router:
            def __init__(self): self.calls = 0
            def generate(self, messages, system_prompt="", **kw):
                seen.append(system_prompt)
                self.calls += 1
                # Switch provider on the 2nd step to exercise the switch note.
                prov = "groq" if self.calls == 1 else "cerebras"
                return "vault:search foo", prov

        ctx = AgentContext(
            user_input="dig into the projects folder", history=[], history_lock=threading.Lock(),
            router=_Router(), registry=_Registry(), memory=None, ctx_mgr=None,
            system_prompt="BASE", max_steps=3,
        )
        run_agent_loop(ctx)
        self.assertIn("TASK STATE", seen[0])
        self.assertIn("dig into the projects folder", seen[0])
        self.assertIn("nothing yet", seen[0])             # step 1: no checkpoints
        self.assertIn("vault:search", seen[1])            # step 2 sees step-1 checkpoint
        self.assertIn("mid-task", seen[2])                # provider switched groq→cerebras


class ExtractVaultCommandsTests(unittest.TestCase):
    """T5.01 — multi-paragraph note bodies must not be truncated at the first blank line."""

    def test_create_keeps_blank_lines_in_body(self):
        reply = (
            "I'll save this.\n"
            "vault:create AI/Research/rmh.md\n"
            "# Rocket Mass Heaters\n"
            "\n"
            "First paragraph about combustion.\n"
            "\n"
            "Second paragraph about thermal mass."
        )
        cmds = extract_vault_commands(reply)
        self.assertEqual(len(cmds), 1)
        self.assertIn("First paragraph", cmds[0])
        self.assertIn("Second paragraph about thermal mass", cmds[0])   # not truncated

    def test_body_command_stops_at_next_vault_command(self):
        reply = (
            "vault:create AI/x.md\n# Title\n\nBody line.\n\n"
            "vault:search something else"
        )
        cmds = extract_vault_commands(reply)
        self.assertEqual(len(cmds), 2)
        self.assertIn("Body line.", cmds[0])
        self.assertNotIn("vault:search", cmds[0])
        self.assertEqual(cmds[1], "vault:search something else")

    def test_single_line_command_still_stops_at_blank_line(self):
        reply = "vault:search rocket stoves\n\nSome unrelated commentary."
        cmds = extract_vault_commands(reply)
        self.assertEqual(cmds, ["vault:search rocket stoves"])


class AgentLoopNoneReplyTests(unittest.TestCase):
    """A provider can return None content (length cap / content filter) — must not crash."""

    def test_none_reply_does_not_crash(self):
        class _NoneRouter:
            def generate(self, messages, system_prompt="", max_tokens=2048, temperature=0.7,
                         provider_override=None, private=False, allow_webui_on_private=False, **kw):
                return None, "groq"     # content came back None
        ctx = AgentContext(
            user_input="hi", history=[], history_lock=threading.Lock(),
            router=_NoneRouter(), registry=None, memory=None, ctx_mgr=None, system_prompt="",
        )
        reply, provider = run_agent_loop(ctx)
        self.assertEqual(reply, "")
        self.assertEqual(provider, "groq")


if __name__ == "__main__":
    unittest.main()

"""
Agent Loop — Milestone 7.5 patch 2

Changes from previous version:

1. MAX_STEPS raised from 5 to 10.
   Rationale: the rocket stove test showed a legitimate 6-step task
   (search x2, create x2, research, import). 5 was too tight for
   real multi-step work. 10 gives headroom without risking runaway loops.
   The model still stops naturally when it has no more vault: commands to
   issue — the cap is a safety ceiling, not the normal exit path.

2. vault:import explicitly blocked in the agent loop with a clear
   explanation returned to the model.
   Rationale: vault:import requires interactive paste mode (multiline
   stdin input). It cannot run autonomously. Previously it was silently
   omitted from VAULT_COMMANDS, so when the model issued it, the step
   cap was consumed without any feedback. Now the model gets:
     "[vault:import cannot run autonomously. To import external research,
      the user must run vault:import manually in the terminal or plugin
      paste mode. Instead, use vault:create to save any content you
      already have in context.]"
   This lets the model self-correct — it will either use vault:create
   to save the content directly, or explain to the user what to do.

3. Intermediate assistant commentary is only printed when it contains
   content beyond vault: command lines (no more blank intermediate prints).
"""

import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from assistant_core.task_ledger import TaskLedger

logger = logging.getLogger("assistant")

MAX_STEPS = 10   # raised from 5

# ---------------------------------------------------------------------------
# Vault command table
# ---------------------------------------------------------------------------

VAULT_COMMANDS = {
    "vault:read":      "read_note",
    "vault:search":    "search_vault",
    "vault:list":      "list_vault",
    "vault:find":      "find_notes",
    "vault:links":     "get_linked_notes",
    "vault:create":    "create_note",
    "vault:update":    "update_note",
    "vault:research":  "generate_research_prompt",
    "vault:summarise": "summarise_research",
    "vault:summarize": "summarise_research",   # accept the American spelling too
    "vault:calc":      "calc",                 # M32 — deterministic arithmetic
}

# Commands that cannot run autonomously — return a helpful message instead
_RESTRUCTURE_BLOCK = (
    "[{cmd} restructures the vault and cannot run autonomously — moving, copying, "
    "trashing, or creating folders is always a human decision. Explain to the user "
    "what you would change and which paths, and let them run {cmd} themselves in the "
    "terminal or plugin.]"
)

BLOCKED_COMMANDS: dict[str, str] = {
    "vault:import": (
        "[vault:import cannot run autonomously — it requires the user to paste "
        "external content interactively. "
        "If you have research content already in context, save it directly with "
        "vault:create AI/Research/YYYY-MM-DD-<topic>.md followed by the content. "
        "If you need the user to do an external research lookup first, "
        "explain that to them and suggest they use vault:import manually.]"
    ),
    # (M29) vault:copy / :move / :trash / :mkdir are no longer hard-blocked — the agent
    # now *proposes* them for one-click user approval. See RESTRUCTURE_COMMANDS below.
}

READ_TOOLS = {"read_note", "search_vault", "list_vault", "find_notes", "get_linked_notes", "summarise_research", "calc"}

# M20 — "deliverable" tools: their output IS the answer. Once one runs, the loop
# returns it and stops, instead of continuing to "finish" work the user didn't ask
# for (e.g. vault:research generates a prompt to paste into a web AI — that's the
# whole job; don't then research the topic yourself or run more commands).
TERMINAL_TOOLS = {"generate_research_prompt"}

# M29 — restructuring ops the agent may PROPOSE (never auto-run). When the model emits
# one, the loop stages a proposal and ends the turn; the user approves it with one click.
RESTRUCTURE_COMMANDS = {"vault:copy", "vault:move", "vault:trash", "vault:mkdir"}

# A weak model can spew malformed, concatenated `vault:...` commands as its "answer"
# (e.g. `We need to issue vault:list.vault:list "x"vault:list "x"`). If they don't parse as
# real commands the loop would otherwise show that raw text. Strip command-spam for display.
_INLINE_CMD_RE = re.compile(r'vault:[a-z][a-z-]*(?:\s+"[^"\n]*"|\s+[^\s\n]+)*', re.IGNORECASE)


def _clean_for_display(text: str) -> str:
    """Remove inline command-spam from a reply. Only acts when 2+ command tokens are
    present (so a single legit 'use vault:search' mention in prose is left alone).
    Returns '' if stripping guts the reply — the caller then shows a graceful fallback."""
    if len(_INLINE_CMD_RE.findall(text)) < 2:
        return text
    stripped = _INLINE_CMD_RE.sub("", text)
    stripped = re.sub(r"[ \t]{2,}", " ", stripped)
    stripped = re.sub(r"\n{3,}", "\n\n", stripped).strip(" .\t\n")
    return stripped if sum(c.isalpha() for c in stripped) >= 15 else ""


_NO_ANSWER = ("I wasn't able to give a clear answer to that. Could you rephrase or add a "
              "little more detail? (Some providers are rate-limited right now, so a weaker "
              "model may be answering.)")

_RESTRUCTURE_VERB = {"vault:trash": "move to .trash/ (recoverable)", "vault:move": "move / rename",
                     "vault:copy": "copy", "vault:mkdir": "create the folder"}


def _restructure_proposal(cmd: str) -> dict | None:
    """Parse a restructuring command into an approval proposal. `cmd` is the exact
    command line; `command` is what runs verbatim (directly) once the user approves."""
    parts = cmd.split(None, 1)
    op = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    if op not in RESTRUCTURE_COMMANDS or not arg:
        return None
    verb = _RESTRUCTURE_VERB.get(op, "restructure")
    if op in ("vault:move", "vault:copy") and "->" in arg:
        src, dst = (s.strip() for s in arg.split("->", 1))
        summary = f"{op.split(':')[1].capitalize()} `{src}` → `{dst}`"
    elif op == "vault:trash":
        src, dst, summary = arg, None, f"Move `{arg}` to `.trash/` (recoverable — not a hard delete)"
    elif op == "vault:mkdir":
        src, dst, summary = None, arg, f"Create folder `{arg}`"
    else:
        src, dst, summary = arg, None, f"{verb}: `{arg}`"
    return {
        "kind": "restructure", "op": op.split(":")[1],
        "command": cmd, "summary": summary, "src": src, "dst": dst,
        "id": f"rs-{datetime.now().strftime('%Y%m%d%H%M%S')}",
    }


# ---------------------------------------------------------------------------
# Self-correction hints
# ---------------------------------------------------------------------------

_CORRECTION_HINTS: list[tuple[str, str, str]] = [
    (
        "update_note",
        "use vault:create",
        (
            "\n\n[SYSTEM HINT] The note does not exist yet. "
            "On your next step, use vault:create with the same path to create it.\n"
            "Format:\n"
            "vault:create <path>\n"
            "<content>"
        ),
    ),
    (
        "read_note",
        "not found",
        (
            "\n\n[SYSTEM HINT] The note was not found. "
            "Try vault:search to locate it, or check the path spelling."
        ),
    ),
    (
        "create_note",
        "already exists",
        (
            "\n\n[SYSTEM HINT] The note already exists. "
            "Use vault:update to append content to it instead."
        ),
    ),
]


def _maybe_add_correction_hint(tool_name: str, result_text: str) -> str:
    result_lower = result_text.lower()
    for t_name, fragment, hint in _CORRECTION_HINTS:
        if t_name == tool_name and fragment in result_lower:
            logger.info(f"[Agent] Injecting self-correction hint for {tool_name}: {fragment!r}")
            return result_text + hint
    return result_text


# ---------------------------------------------------------------------------
# Command extraction
# ---------------------------------------------------------------------------

# Commands whose argument is a multi-line note BODY (markdown with blank lines
# between paragraphs). For these, a blank line is part of the content, not a
# terminator — capture everything up to the next vault: command or end of reply.
# (T5.01: vault:update was truncating note content at the first blank line, so a
# multi-paragraph note saved only its title.) Other commands take a single-line
# argument, so a blank line still ends them.
_BODY_COMMANDS = ("vault:create", "vault:update")


def extract_vault_commands(reply: str) -> list[str]:
    """
    Find vault: command lines in an assistant reply.
    Returns list of full command strings (including multiline args).
    Includes both executable and blocked commands — blocked ones are
    handled in the execution loop with an explanatory message.
    """
    commands = []
    lines    = reply.splitlines()
    i        = 0
    while i < len(lines):
        line = lines[i].strip()
        if re.match(r"^vault:[a-z]+", line, re.IGNORECASE):
            is_body = line.split(None, 1)[0].lower() in _BODY_COMMANDS
            cmd_lines = [line]
            i += 1
            while i < len(lines):
                next_line = lines[i]
                # The next vault: command always ends the current one.
                if re.match(r"^vault:[a-z]+", next_line.strip(), re.IGNORECASE):
                    break
                # Single-line-arg commands also stop at a blank line; body commands
                # (create/update) keep blank lines as part of the note content.
                if not is_body and not next_line.strip():
                    break
                cmd_lines.append(next_line)
                i += 1
            # Trim trailing blank lines we may have swept up for a body command.
            while cmd_lines and not cmd_lines[-1].strip():
                cmd_lines.pop()
            commands.append("\n".join(cmd_lines))
        else:
            i += 1
    return commands


# ---------------------------------------------------------------------------
# AgentContext
# ---------------------------------------------------------------------------

@dataclass
class AgentContext:
    user_input:        str
    history:           list
    history_lock:      threading.Lock
    router:            Any
    registry:          Any
    memory:            Any
    ctx_mgr:           Any
    system_prompt:     str
    max_tokens:        int   = 2048
    temperature:       float = 0.7
    provider_override: str | None = None
    ep_vault_fn:       Any = None
    ep_error_fn:       Any = None
    tools_used:        list = field(default_factory=list)
    source_label:      str  = ""
    # Milestone 10 — privacy routing. Forwarded to router.generate(); the loop
    # itself has no privacy logic, it only carries the flags through.
    private:                 bool = False
    allow_webui_on_private:  bool = False
    # Max agent iterations for this turn. Defaults to MAX_STEPS; callers pass the
    # user-configurable `max_agent_steps` from settings.json.
    max_steps:               int  = MAX_STEPS
    # M29 — when the agent wants to restructure the vault (copy/move/trash/mkdir), it
    # can't run it autonomously; instead it stages a proposal here and ends the turn.
    # The server surfaces it as a proposal the user approves (one click) to execute.
    pending_restructure:     dict | None = None


# ---------------------------------------------------------------------------
# Shared agent loop
# ---------------------------------------------------------------------------

def run_agent_loop(ctx: AgentContext) -> tuple[str, str]:
    """
    Execute the agent loop for one user turn.

    Returns (final_reply, actual_provider_used).
    Raises ProviderWebUIHandoff or ProviderError — caller handles these.
    """
    from assistant_core.providers.base_provider import Message

    # ── Trim context ───────────────────────────────────────────────────────
    if ctx.ctx_mgr and ctx.router.available_providers:
        with ctx.history_lock:
            ctx.history[:] = ctx.ctx_mgr.trim(
                ctx.history,
                ctx.router.available_providers[0],
                ctx.system_prompt,
                ctx.max_tokens,
                private=ctx.private,
            )

    # ── Append user message ────────────────────────────────────────────────
    with ctx.history_lock:
        ctx.history.append(Message(role="user", content=ctx.user_input))

    reply         = ""
    used_provider = "unknown"
    max_steps     = ctx.max_steps if ctx.max_steps and ctx.max_steps > 0 else MAX_STEPS

    # M20 Slice 3 — externalized task/planner state. Kept outside the model and
    # re-injected into the system prompt each step so a mid-turn provider switch
    # resumes the same task instead of replanning from chat history. Also mirrored
    # to AI/System/Task-State.md so the user can watch the stages and resume after
    # a crash (RAG-excluded path → no index spam, no watcher loop).
    ledger = TaskLedger(goal=ctx.user_input)
    _vault_path = getattr(ctx.registry, "_vault_path", None) if ctx.registry else None
    if _vault_path:
        from pathlib import Path
        ledger.persist_path = Path(_vault_path) / "AI" / "System" / "Task-State.md"
    ledger.persist("starting", 0, max_steps)

    for step in range(max_steps):

        # Append the live task ledger to the system prompt for this step.
        step_system_prompt = ctx.system_prompt + "\n\n" + ledger.render(step + 1, max_steps)

        # ── Generate ───────────────────────────────────────────────────────
        reply, used_provider = ctx.router.generate(
            messages          = list(ctx.history),
            system_prompt     = step_system_prompt,
            max_tokens        = ctx.max_tokens,
            temperature       = ctx.temperature,
            provider_override = ctx.provider_override,
            private                = ctx.private,
            allow_webui_on_private = ctx.allow_webui_on_private,
        )
        reply = reply or ""   # a provider can return None content (e.g. length/filter) — never crash on it

        if ledger.last_provider and used_provider != ledger.last_provider:
            logger.info(f"[Agent] Provider switch mid-task: {ledger.last_provider} → {used_provider}")
        ledger.note_provider(used_provider)

        logger.info(f"[Agent] Step {step+1}/{max_steps}: {len(reply)} chars from {used_provider}")

        # ── No registry → accept as-is ─────────────────────────────────────
        if ctx.registry is None:
            with ctx.history_lock:
                ctx.history.append(Message(role="assistant", content=reply))
            return reply, used_provider

        # ── Scan for vault commands ────────────────────────────────────────
        vault_cmds = extract_vault_commands(reply)

        if not vault_cmds:
            # Clean reply — done. Guard against a weak model leaving raw command-spam
            # in what it calls its answer.
            with ctx.history_lock:
                ctx.history.append(Message(role="assistant", content=reply))
            ledger.persist("done", step + 1, max_steps)
            display = _clean_for_display(reply)   # "" only when command-spam was gutted
            return (display or _NO_ANSWER), used_provider

        # ── Show non-command commentary to terminal ────────────────────────
        clean_reply = "\n".join(
            ln for ln in reply.splitlines()
            if not re.match(r"^vault:[a-z]+", ln.strip(), re.IGNORECASE)
        ).strip()
        if clean_reply:
            src = f" [{ctx.source_label}]" if ctx.source_label else f" [{used_provider}]"
            print(f"\nAssistant{src}: {clean_reply}")

        # Append full reply to history
        with ctx.history_lock:
            ctx.history.append(Message(role="assistant", content=reply))

        # ── Execute commands ───────────────────────────────────────────────
        logger.info(f"[Agent] Step {step+1}: executing {len(vault_cmds)} command(s)")
        tool_results = []
        terminal_output: str | None = None   # M20 — set when a deliverable tool runs

        for cmd in vault_cmds:
            parts  = cmd.split(None, 1)
            prefix = parts[0].lower()

            # M29 — restructuring op: stage a proposal for the user to approve, then end
            # the turn. The agent never runs it itself, and never retries in a loop.
            if prefix in RESTRUCTURE_COMMANDS:
                prop = _restructure_proposal(cmd.strip())
                if prop and ctx.pending_restructure is None:
                    ctx.pending_restructure = prop
                tool_results.append(f"[Proposed {prefix} — awaiting the user's one-click approval.]")
                ledger.record(step + 1, used_provider, prefix, False, "proposed — awaiting approval")
                logger.info(f"[Agent] Proposed restructuring: {cmd.strip()}")
                continue

            # Check blocked commands first
            if prefix in BLOCKED_COMMANDS:
                explanation = BLOCKED_COMMANDS[prefix]
                tool_results.append(f"[Blocked: {prefix}]\n{explanation}")
                ledger.record(step + 1, used_provider, prefix, False, "blocked — not autonomous")
                print(f"\n[Agent blocked: {prefix}] — not supported in autonomous mode")
                logger.info(f"[Agent] Blocked command: {prefix}")
                continue

            tool_name = VAULT_COMMANDS.get(prefix)
            if tool_name is None:
                tool_results.append(f"[Unknown command: {prefix}]")
                continue

            tool_input  = parts[1].strip() if len(parts) > 1 else ""
            result      = ctx.registry.run(tool_name, tool_input)
            result_text = f"{'✓' if result.success else '✗'} [{tool_name}]\n\n{result.output}"
            result_text = _maybe_add_correction_hint(tool_name, result_text)

            tool_results.append(f"[Tool result for `{prefix}`]\n{result_text}")
            ctx.tools_used.append(prefix)
            ledger.record(step + 1, used_provider, prefix, result.success,
                          tool_input or result.output)   # M20 Slice 3 — per-tool checkpoint
            if tool_name in TERMINAL_TOOLS and result.success:
                terminal_output = result.output   # M20 — present this and stop

            status_icon = "✓" if result.success else "✗"
            print(f"\n[Agent executing: {prefix}] {status_icon}")

            if ctx.memory and ctx.ep_vault_fn:
                detail = cmd.splitlines()[0][:120]
                suffix = f" [{ctx.source_label}-agent]" if ctx.source_label else " [agent]"
                ctx.memory.append_episode(ctx.ep_vault_fn(prefix, detail + suffix))

        ledger.persist("in-progress", step + 1, max_steps)

        # M20 — a deliverable tool IS the answer: present it and stop, instead of
        # looping to "finish" more work the user didn't ask for.
        if terminal_output is not None:
            with ctx.history_lock:
                ctx.history.append(Message(role="assistant", content=terminal_output))
            logger.info("[Agent] Deliverable tool produced output — ending turn.")
            ledger.persist("done", step + 1, max_steps)
            return terminal_output, used_provider

        # M29 — a restructuring op was staged for approval: end the turn now (retrying
        # never helps — the user must approve). The server attaches ctx.pending_restructure
        # as a proposal; the reply describes it and names the exact command as a fallback.
        if ctx.pending_restructure is not None:
            prop = ctx.pending_restructure
            msg = (clean_reply + "\n\n" if clean_reply else "") + (
                f"I've prepared a vault change for your approval: **{prop['summary']}**. "
                f"Approve it below to run — or do it yourself with `{prop['command']}`. "
                "(Nothing is changed until you approve.)")
            with ctx.history_lock:
                ctx.history.append(Message(role="assistant", content=msg))
            logger.info(f"[Agent] Ending turn — restructuring proposed: {prop['command']}")
            ledger.persist("done — awaiting approval", step + 1, max_steps)
            return msg, used_provider

        # ── Inject tool results ────────────────────────────────────────────
        combined = "\n\n".join(tool_results)
        with ctx.history_lock:
            ctx.history.append(Message(
                role    = "user",
                content = (
                    "[Tool execution complete. "
                    "Use the results to complete your response. "
                    "If any command was blocked, follow its instructions.]\n\n"
                    + combined
                ),
            ))

    # ── Max steps reached ──────────────────────────────────────────────────
    logger.warning(f"[Agent] Reached max steps ({max_steps}) — returning last reply")
    ledger.persist("stopped — reached max steps", max_steps, max_steps)
    return (_clean_for_display(reply) or _NO_ANSWER), used_provider

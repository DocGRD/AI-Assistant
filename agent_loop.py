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
from typing import Any

logger = logging.getLogger("assistant")

MAX_STEPS = 10   # raised from 5

# ---------------------------------------------------------------------------
# Vault command table
# ---------------------------------------------------------------------------

VAULT_COMMANDS = {
    "vault:read":      "read_note",
    "vault:search":    "search_vault",
    "vault:list":      "list_vault",
    "vault:links":     "get_linked_notes",
    "vault:create":    "create_note",
    "vault:update":    "update_note",
    "vault:research":  "generate_research_prompt",
    "vault:summarise": "summarise_research",
}

# Commands that cannot run autonomously — return a helpful message instead
BLOCKED_COMMANDS: dict[str, str] = {
    "vault:import": (
        "[vault:import cannot run autonomously — it requires the user to paste "
        "external content interactively. "
        "If you have research content already in context, save it directly with "
        "vault:create AI/Research/YYYY-MM-DD-<topic>.md followed by the content. "
        "If you need the user to do an external research lookup first, "
        "explain that to them and suggest they use vault:import manually.]"
    ),
}

READ_TOOLS = {"read_note", "search_vault", "list_vault", "get_linked_notes", "summarise_research"}


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
            cmd_lines = [line]
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if not next_line.strip():
                    break
                if re.match(r"^vault:[a-z]+", next_line.strip(), re.IGNORECASE):
                    break
                cmd_lines.append(next_line)
                i += 1
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


# ---------------------------------------------------------------------------
# Shared agent loop
# ---------------------------------------------------------------------------

def run_agent_loop(ctx: AgentContext) -> tuple[str, str]:
    """
    Execute the agent loop for one user turn.

    Returns (final_reply, actual_provider_used).
    Raises ProviderWebUIHandoff or ProviderError — caller handles these.
    """
    from providers.base_provider import Message

    # ── Trim context ───────────────────────────────────────────────────────
    if ctx.ctx_mgr and ctx.router.available_providers:
        with ctx.history_lock:
            ctx.history[:] = ctx.ctx_mgr.trim(
                ctx.history,
                ctx.router.available_providers[0],
                ctx.system_prompt,
                ctx.max_tokens,
            )

    # ── Append user message ────────────────────────────────────────────────
    with ctx.history_lock:
        ctx.history.append(Message(role="user", content=ctx.user_input))

    reply         = ""
    used_provider = "unknown"

    for step in range(MAX_STEPS):

        # ── Generate ───────────────────────────────────────────────────────
        reply, used_provider = ctx.router.generate(
            messages          = list(ctx.history),
            system_prompt     = ctx.system_prompt,
            max_tokens        = ctx.max_tokens,
            temperature       = ctx.temperature,
            provider_override = ctx.provider_override,
            private                = ctx.private,
            allow_webui_on_private = ctx.allow_webui_on_private,
        )

        logger.info(f"[Agent] Step {step+1}/{MAX_STEPS}: {len(reply)} chars from {used_provider}")

        # ── No registry → accept as-is ─────────────────────────────────────
        if ctx.registry is None:
            with ctx.history_lock:
                ctx.history.append(Message(role="assistant", content=reply))
            return reply, used_provider

        # ── Scan for vault commands ────────────────────────────────────────
        vault_cmds = extract_vault_commands(reply)

        if not vault_cmds:
            # Clean reply — done
            with ctx.history_lock:
                ctx.history.append(Message(role="assistant", content=reply))
            return reply, used_provider

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

        for cmd in vault_cmds:
            parts  = cmd.split(None, 1)
            prefix = parts[0].lower()

            # Check blocked commands first
            if prefix in BLOCKED_COMMANDS:
                explanation = BLOCKED_COMMANDS[prefix]
                tool_results.append(f"[Blocked: {prefix}]\n{explanation}")
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

            status_icon = "✓" if result.success else "✗"
            print(f"\n[Agent executing: {prefix}] {status_icon}")

            if ctx.memory and ctx.ep_vault_fn:
                detail = cmd.splitlines()[0][:120]
                suffix = f" [{ctx.source_label}-agent]" if ctx.source_label else " [agent]"
                ctx.memory.append_episode(ctx.ep_vault_fn(prefix, detail + suffix))

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
    logger.warning(f"[Agent] Reached max steps ({MAX_STEPS}) — returning last reply")
    return reply, used_provider

"""The `vault:` command vocabulary and its dispatcher.

Maps a `vault:<verb>` string to a registered tool and runs it. Read-tool results
are injected into chat history (outside the agent loop) so the model can use them.
Shared by the terminal loop in `app.py`; the agent loop has its own execution path.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from assistant_core.episodes import ep_vault
from assistant_core.providers.base_provider import Message

if TYPE_CHECKING:
    from assistant_core.tools.tool_registry import ToolRegistry
    from assistant_core.memory.memory_manager import MemoryManager

VAULT_COMMANDS = {
    "vault:read":      ("read_note",                "Usage: vault:read <note name or path>"),
    "vault:search":    ("search_vault",             "Usage: vault:search <query>"),
    "vault:list":      ("list_vault",               "Usage: vault:list [subfolder]"),
    "vault:find":      ("find_notes",               "Usage: vault:find <glob>  e.g. 06 - Projects/**/*.md"),
    "vault:links":     ("get_linked_notes",         "Usage: vault:links <note name or path>"),
    "vault:create":    ("create_note",              "Usage: vault:create <path>\n<content>"),
    "vault:update":    ("update_note",              "Usage: vault:update <path>\n<content to append>"),
    "vault:copy":      ("copy_path",                "Usage: vault:copy <src> -> <dst>"),
    "vault:move":      ("move_path",                "Usage: vault:move <src> -> <dst>"),
    "vault:trash":     ("trash_path",               "Usage: vault:trash <path>  (recoverable → .trash/)"),
    "vault:mkdir":     ("mkdir_vault",              "Usage: vault:mkdir <path>"),
    "vault:research":  ("generate_research_prompt", "Usage: vault:research <question>"),
    "vault:import":    ("import_research",          "Usage: vault:import\n<paste external AI response>"),
    "vault:summarise": ("summarise_research",       "Usage: vault:summarise <path to research note>"),
    "vault:summarize": ("summarise_research",       "Usage: vault:summarize <path to research note>"),
    "vault:update-providers": ("update_providers",  "Usage: vault:update-providers [provider|apply]"),
}

READ_TOOLS = {"read_note", "search_vault", "list_vault", "find_notes", "get_linked_notes", "summarise_research"}

# Tools that may run with no input (e.g. vault:list root, vault:update-providers propose).
NO_INPUT_OK = {"list_vault", "update_providers"}

VALID_PROVIDERS = ("groq", "google", "cerebras", "webui", "auto")


def handle_vault_command(
    raw:          str,
    registry:     "ToolRegistry",
    history:      list[Message],
    memory:       "MemoryManager | None",
    logger:       logging.Logger,
    _agent_mode:  bool = False,  # True = called from agent loop, skip duplicate history injection
) -> str | None:
    parts  = raw.split(None, 1)
    prefix = parts[0].lower()

    if prefix not in VAULT_COMMANDS:
        return None

    tool_name, usage = VAULT_COMMANDS[prefix]
    tool_input = parts[1].strip() if len(parts) > 1 else ""

    if not tool_input and tool_name not in NO_INPUT_OK:
        return f"Missing input. {usage}"

    result = registry.run(tool_name, tool_input)

    # Inject into history for read tools (skip in agent mode — already managed)
    if result.success and tool_name in READ_TOOLS and not _agent_mode:
        history.append(Message(
            role    = "user",
            content = f"[Vault context loaded by tool '{tool_name}']\n\n{result.output}",
        ))
        history.append(Message(
            role    = "assistant",
            content = "Vault content loaded. Ready to help.",
        ))
        logger.info(f"[Vault] '{tool_name}' injected into history")

    detail = tool_input.splitlines()[0][:120] if tool_input else "(vault root)"
    if memory and not _agent_mode:
        memory.append_episode(ep_vault(tool_name, detail))

    return f"{'✓' if result.success else '✗'} [{tool_name}]\n\n{result.output}"

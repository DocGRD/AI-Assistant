"""
Assistant Core — Milestone 6 (HTTP server enabled)

Episode notes are written live to the vault as each event happens.
A crash or force-quit loses nothing that was already appended.
The HTTP server runs as a third daemon thread alongside the watcher,
exposing /chat, /status, and /history to the Obsidian plugin.
"""

import logging
import threading
from datetime import datetime as _dt
from pathlib import Path
from typing import Optional

# FIX 3: single top-level import — removed the duplicate inside main()
from server import AssistantServer

from config.config_manager import ConfigManager
from config.logger import setup_logger, set_verbose, is_verbose
from providers.provider_router import ProviderRouter
from providers.base_provider import Message, ProviderError
from providers.model_registry import estimate_tokens
from memory.memory_manager import MemoryManager
from memory.context_manager import ContextManager
from tools.tool_registry import ToolRegistry
from watcher.vault_watcher import VaultWatcher


# ---------------------------------------------------------------------------
# Episode line formatters
# FIX 1+2: Restored the four ep_* functions that are called throughout the
# file. The submitted version defined unused EPISODE_*_PREFIX constants but
# never completed the refactor, leaving these names undefined (NameError).
# ---------------------------------------------------------------------------

def _ts() -> str:
    return _dt.now().strftime("%H:%M")


def ep_vault(tool: str, detail: str) -> str:
    return f"- **{_ts()}** `{tool}` — {detail}\n"


def ep_remember(fact: str) -> str:
    return f"- **{_ts()}** Remembered: {fact}\n"


def ep_chat(user: str, assistant: str) -> str:
    reply_lines = assistant.strip().splitlines()
    indented    = "\n> ".join(reply_lines)
    return f"\n**{_ts()} — You:** {user}\n> {indented}\n"


def ep_error(detail: str) -> str:
    return f"- **{_ts()}** ⚠ {detail}\n"


# ---------------------------------------------------------------------------
# Startup diagnostics
# FIX 5: Changed config type hint from Dict[str,Any] to ConfigManager since
# that is what is actually passed. ConfigManager has .get() so behaviour is
# unchanged; the annotation now matches reality.
# ---------------------------------------------------------------------------

def run_startup_diagnostics(
    config: ConfigManager,
    router: ProviderRouter,
    registry: Optional[ToolRegistry],
    memory: Optional[MemoryManager],
    logger: logging.Logger,
) -> None:
    """Run startup diagnostics to verify system readiness."""
    checks: dict[str, bool] = {}

    config_path = Path(__file__).parent / "config" / "settings.json"
    checks["Config Loaded"] = config_path.exists()

    vault_path = config.get("vault_path", "")
    checks["Vault Found"] = bool(vault_path) and Path(vault_path).exists()

    logs_dir = Path(__file__).parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    checks["Logs Ready"] = logs_dir.exists()

    checks["Memory Ready"] = memory is not None

    for name, available in router.status().items():
        checks[f"Provider: {name.capitalize()}"] = available

    tool_count = len(registry.tool_names) if registry else 0
    checks[f"Vault Tools ({tool_count})"] = tool_count > 0

    sep = "=" * 48
    print("\n" + sep)
    print("  AI ASSISTANT — Startup Check")
    print(sep)
    for name, passed in checks.items():
        print(f"  {'✓' if passed else '✗'}  {name}")
    print(sep)

    avail = router.available_providers
    if avail:
        print(f"\n  Active provider  : {config.get('default_provider', 'groq').upper()}")
        if len(avail) > 1:
            print(f"  Fallback provider: {config.get('fallback_provider', 'google').upper()}")
    else:
        print("\n  ✗  No providers available. Add API keys to config/settings.json.")

    print("\n  Assistant Online")
    print(sep + "\n")

    failed = [n for n, p in checks.items() if not p]
    if failed:
        logger.warning(f"Startup checks failed: {', '.join(failed)}")
    else:
        logger.info("All startup checks passed")


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

BASE_SYSTEM_PROMPT = """You are a helpful AI development and study assistant integrated with Obsidian.
You help with software development, Scripture study, research, planning, and knowledge management.
You are concise, accurate, and practical. When you don't know something, say so clearly.
When vault content is provided in the conversation, use it to give specific grounded answers.
When the user asks you to search the internet, generate an optimized research prompt they can paste into a web-based AI instead.
When the user types 'remember: <something>', acknowledge that the fact has been saved."""


def build_system_prompt(memory_context: str) -> str:
    if memory_context.strip():
        return BASE_SYSTEM_PROMPT + "\n\n" + memory_context
    return BASE_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Vault command dispatcher
# ---------------------------------------------------------------------------

VAULT_COMMANDS = {
    "vault:read":      ("read_note",                "Usage: vault:read <note name or path>"),
    "vault:search":    ("search_vault",             "Usage: vault:search <query>"),
    "vault:list":      ("list_vault",               "Usage: vault:list [subfolder]"),
    "vault:links":     ("get_linked_notes",         "Usage: vault:links <note name or path>"),
    "vault:create":    ("create_note",              "Usage: vault:create <path>\n<content>"),
    "vault:update":    ("update_note",              "Usage: vault:update <path>\n<content to append>"),
    "vault:research":  ("generate_research_prompt", "Usage: vault:research <question>"),
    "vault:import":    ("import_research",          "Usage: vault:import\n<paste external AI response>"),
    "vault:summarise": ("summarise_research",       "Usage: vault:summarise <path to research note>"),
}

# Read tools inject their output into the AI context window
READ_TOOLS = {"read_note", "search_vault", "list_vault", "get_linked_notes", "summarise_research"}


def handle_vault_command(
    raw: str,
    registry: ToolRegistry,
    history: list[Message],
    memory: Optional[MemoryManager],
    logger: logging.Logger,
) -> Optional[str]:
    """
    Run a vault: command.
    Returns formatted output string, or None if prefix is unrecognised.
    Appends a one-line entry to the episode file immediately.
    """
    parts  = raw.split(None, 1)
    prefix = parts[0].lower()

    if prefix not in VAULT_COMMANDS:
        return None

    tool_name, usage = VAULT_COMMANDS[prefix]
    tool_input = parts[1].strip() if len(parts) > 1 else ""

    if not tool_input and tool_name not in ("list_vault",):
        return f"Missing input. {usage}"

    result = registry.run(tool_name, tool_input)

    # Inject content into AI context window for read operations
    if result.success and tool_name in READ_TOOLS:
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
    if memory:
        memory.append_episode(ep_vault(tool_name, detail))

    return f"{'✓' if result.success else '✗'} [{tool_name}]\n\n{result.output}"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    config = ConfigManager()
    logger = setup_logger(config.get("log_level", "INFO"), verbose=False)
    logger.info("Assistant starting — Milestone 6 (HTTP server enabled)")

    router = ProviderRouter(config.all())

    vault_path = config.get("vault_path", "")
    registry: Optional[ToolRegistry]  = None
    memory:   Optional[MemoryManager] = None
    ctx_mgr:  Optional[ContextManager]= None

    if vault_path and Path(vault_path).exists():
        registry = ToolRegistry(vault_path)
        memory   = MemoryManager(vault_path)
        ctx_mgr  = ContextManager(router.registry)
    else:
        logger.warning("Vault path not set or missing — vault tools and memory disabled.")

    memory_context = memory.load_context() if memory else ""
    system_prompt  = build_system_prompt(memory_context)

    # Open the episode file before anything else so a crash loses nothing
    if memory:
        memory.open_episode()

    run_startup_diagnostics(config, router, registry, memory, logger)

    if not router.available_providers:
        print("No AI providers available. Add API keys to config/settings.json.\n")
        print("  Groq   (free): https://console.groq.com")
        print("  Google (free): https://aistudio.google.com/app/apikey\n")
        return

    # history must exist before the HTTP server is constructed —
    # the server holds a reference to this list so both threads share it.
    history:    list[Message] = []
    tools_used: list[str]     = []

    # ── Start vault watcher ───────────────────────────────────────────────
    watcher: Optional[VaultWatcher]        = None
    watcher_thread: Optional[threading.Thread] = None

    if vault_path and Path(vault_path).exists():
        try:
            watcher = VaultWatcher(
                config.all(),
                poll_interval=config.get("watcher_poll_interval", 5),
            )
            watcher_thread = threading.Thread(target=watcher.run, daemon=True)
            watcher_thread.start()
            logger.info("[Main] Vault watcher started in background thread")
            print("\n[Vault watcher active in background]\n")
        except Exception as exc:
            logger.error(f"[Main] Failed to start watcher: {exc}")
            print(f"Warning: Watcher failed to start: {exc}\n")
    else:
        logger.warning("[Main] Vault path not available — watcher disabled")

    # ── Start HTTP server (Milestone 6) ───────────────────────────────────
    # FIX 3: import already at top — no second import here
    http_server: Optional[AssistantServer] = None

    if vault_path and Path(vault_path).exists():
        try:
            http_server = AssistantServer(
                router        = router,
                memory        = memory,
                registry      = registry,
                history       = history,
                config        = config.all(),
                system_prompt = system_prompt,
                ep_chat_fn    = ep_chat,
                ep_error_fn   = ep_error,
            )
            http_server.start()
        except Exception as exc:
            logger.error(f"[Main] Failed to start HTTP server: {exc}")
            print(f"Warning: HTTP server failed to start: {exc}\n")
    else:
        logger.warning("[Main] Vault path not available — HTTP server disabled")

    # ── Print help ────────────────────────────────────────────────────────
    print("Type your message and press Enter.")
    print("Vault read   : vault:read | vault:search | vault:list | vault:links")
    print("Vault write  : vault:create | vault:update")
    print("Memory       : remember: <fact>")
    print("Info         : tools | models | context | status | verbose on/off")
    print("Session      : clear | exit\n")
    if http_server and http_server.is_available():
        host = config.get("host", "127.0.0.1")
        port = config.get("port", 8765)
        print(f"Obsidian plugin: connect to http://{host}:{port}")
        print(f"API docs       : http://{host}:{port}/docs\n")

    # ── Normal chat loop ──────────────────────────────────────────────────
    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nShutting down...")
            break

        if not user_input:
            continue

        # ── Exit ──────────────────────────────────────────────────────────
        if user_input.lower() in ("exit", "quit"):
            print("Shutting down...")
            if watcher:
                watcher.stop()
                logger.info("[Main] Stopping watcher...")
            if http_server:
                http_server.stop()
                logger.info("[Main] HTTP server stopped")
            break

        # ── Clear ─────────────────────────────────────────────────────────
        if user_input.lower() == "clear":
            history.clear()
            print("[Conversation history cleared — episode log unaffected]\n")
            continue

        # ── Verbose ───────────────────────────────────────────────────────
        if user_input.lower() in ("verbose on", "verbose off"):
            enable = user_input.lower() == "verbose on"
            set_verbose(enable)
            state = "ON — logs appear in console" if enable else "OFF — logs in assistant.log only"
            print(f"[Verbose {state}]\n")
            continue

        # ── Status ────────────────────────────────────────────────────────
        if user_input.lower() == "status":
            print("\n--- Status ---")
            for name, avail in router.status().items():
                print(f"  {'✓' if avail else '✗'}  {name.capitalize()}")
            print(f"  Verbose: {'ON' if is_verbose() else 'OFF'}")
            if http_server and http_server.is_available():
                host = config.get("host", "127.0.0.1")
                port = config.get("port", 8765)
                print(f"  HTTP API: http://{host}:{port}")
            if ctx_mgr and router.available_providers:
                active = router.available_providers[0]
                print(f"  Context: {ctx_mgr.report(history, active, system_prompt)}")
            print("--------------\n")
            continue

        # ── Models ────────────────────────────────────────────────────────
        if user_input.lower() == "models":
            print(router.capability_report())
            continue

        # ── Context ───────────────────────────────────────────────────────
        if user_input.lower() == "context":
            if ctx_mgr and router.available_providers:
                active = router.available_providers[0]
                print(f"\n  {ctx_mgr.report(history, active, system_prompt)}")
                print(f"  System prompt  : ~{estimate_tokens([], system_prompt)} tokens")
                print(f"  History entries: {len(history)}\n")
            else:
                print("[Context manager not available]\n")
            continue

        # ── Tools ─────────────────────────────────────────────────────────
        if user_input.lower() == "tools":
            if registry is None:
                print("[Vault tools not available — set vault_path in settings.json]\n")
            else:
                print("\n--- Available Tools ---")
                for t in registry.list_tools():
                    print(f"  {t['name']:<22} {t['description']}")
                print("----------------------\n")
            continue

        # ── Remember ──────────────────────────────────────────────────────
        if user_input.lower().startswith("remember:"):
            fact = user_input[len("remember:"):].strip()
            if memory:
                result = memory.remember(fact)
                memory.append_episode(ep_remember(fact))
                print(f"\n{result}\n")
            else:
                print("[Memory not available — vault path not set]\n")
            continue

        # ── Vault commands ────────────────────────────────────────────────
        if user_input.lower().startswith("vault:"):
            if registry is None:
                print("[Vault tools not available — set vault_path in settings.json]\n")
                continue

            if user_input.lower().startswith("vault:import"):
                print("[Multiline mode — paste your research, then type '---end' on a new line]\n")
                pasted_lines = []
                while True:
                    try:
                        line = input()
                    except (KeyboardInterrupt, EOFError):
                        print("\n[Import cancelled]\n")
                        break
                    if line.strip() == "---end":
                        break
                    pasted_lines.append(line)

                if pasted_lines:
                    import_input = "\n".join(pasted_lines)
                    output = handle_vault_command(
                        "vault:import " + import_input, registry, history, memory, logger
                    )
                    if output is not None:
                        tools_used.append("vault:import")
                        print(f"\n{output}\n")
                continue

            output = handle_vault_command(user_input, registry, history, memory, logger)
            if output is not None:
                tools_used.append(user_input.split(None, 1)[0].lower())
                print(f"\n{output}\n")
                continue

        # ── Normal AI chat ────────────────────────────────────────────────
        if ctx_mgr and router.available_providers:
            history = ctx_mgr.trim(
                history,
                router.available_providers[0],
                system_prompt,
                config.get("max_tokens", 2048),
            )

        history.append(Message(role="user", content=user_input))
        logger.info(f"User: {user_input[:80]}{'...' if len(user_input) > 80 else ''}")

        try:
            reply = router.generate(
                messages      = history,
                system_prompt = system_prompt,
                max_tokens    = config.get("max_tokens", 2048),
                temperature   = config.get("temperature", 0.7),
            )
        except ProviderError as exc:
            print(f"\n[Error] {exc}\n")
            logger.error(f"Provider error: {exc}")
            history.pop()
            if memory:
                memory.append_episode(ep_error(str(exc)[:120]))
            continue

        history.append(Message(role="assistant", content=reply))
        logger.info(f"Assistant replied ({len(reply)} chars)")
        print(f"\nAssistant: {reply}\n")

        if memory:
            memory.append_episode(ep_chat(user_input, reply))

    # ------------------------------------------------------------------
    # Shutdown: write footer (error summary + tools used)
    # ------------------------------------------------------------------
    logger.info("Assistant shutting down.")

    if watcher_thread and watcher_thread.is_alive():
        logger.info("[Main] Waiting for watcher thread to stop...")
        watcher_thread.join(timeout=2)

    if memory:
        memory.close_episode(
            error_summary = router.session_error_summary(),
            tools_used    = list(set(tools_used)),
        )
        print("Session footer written. Goodbye.\n")
    else:
        print("Goodbye.\n")


if __name__ == "__main__":
    main()
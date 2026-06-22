"""
Assistant Core — Milestone 7.5 (Hardening)

Fixes applied:
  BUG-001  Agent loop: assistant replies containing vault: commands are now
           executed automatically. The tool result is injected back into
           history and the model is called again for a final response.
  BUG-002  Headless mode: --headless flag (or auto-detect via stdin.isatty())
           skips the chat loop and keeps watcher + HTTP server running under
           systemd with no terminal attached.
  BUG-003  Full system_prompt (with User-Profile and memory) is now passed
           into VaultWatcher → RequestHandler so vault-mode responses have
           the same identity as the terminal loop.
  BUG-004  ep_handoff() is now called in all three handoff paths: terminal
           loop, server.py (via ep_handoff_fn), and watcher (via request_handler).
  BUG-007  Log rotation moved to TimedRotatingFileHandler in config/logger.py.
  BUG-008  venv check: if groq/google-genai are not importable, print a clear
           activation instruction before crashing.
"""

import sys
import logging
import threading
import time
import logging
import re
from datetime import datetime as _dt
from pathlib import Path
from turtle import mode

logger = logging.getLogger("assistant")

# BUG-008: detect missing venv early with a clear user-facing message
def _check_venv() -> None:
    missing = []
    try:
        import groq  # noqa: F401
    except ImportError:
        missing.append("groq")
    try:
        from google import genai  # noqa: F401
    except ImportError:
        missing.append("google-genai")

    if missing:
        print("\n" + "=" * 56)
        print("  MISSING PACKAGES: " + ", ".join(missing))
        print("  You may not be inside the virtual environment.")
        print()
        print("  Windows:  .venv\\Scripts\\Activate.ps1")
        print("  Linux:    source .venv/bin/activate")
        print()
        print("  Then run: pip install -r requirements.txt")
        print("=" * 56 + "\n")
        sys.exit(1)

_check_venv()

from server import AssistantServer

from config.config_manager import ConfigManager
from config.logger import setup_logger, set_verbose, is_verbose
from providers.provider_router import ProviderRouter
from providers.base_provider import Message, ProviderError, ProviderWebUIHandoff
from providers.model_registry import estimate_tokens
from memory.memory_manager import MemoryManager
from memory.context_manager import ContextManager
from tools.tool_registry import ToolRegistry
from watcher.vault_watcher import VaultWatcher
from agent_loop import AgentContext, run_agent_loop, extract_vault_commands

# ---------------------------------------------------------------------------
# Episode line formatters
# ---------------------------------------------------------------------------

def _ts() -> str:
    return _dt.now().strftime("%H:%M")


def ep_vault(tool: str, detail: str) -> str:
    return f"- **{_ts()}** `{tool}` — {detail}\n"


def ep_remember(fact: str) -> str:
    return f"- **{_ts()}** Remembered: {fact}\n"


def ep_chat(user: str, assistant: str, provider: str = "") -> str:
    reply_lines = assistant.strip().splitlines()
    indented    = "\n> ".join(reply_lines)
    tag         = f" [{provider}]" if provider else ""
    return f"\n**{_ts()}{tag} — You:** {user}\n> {indented}\n"


def ep_error(detail: str) -> str:
    return f"- **{_ts()}** ⚠ {detail}\n"


def ep_handoff(direction: str, detail: str) -> str:
    return f"- **{_ts()}** 🌐 Web handoff {direction} — {detail}\n"


# ---------------------------------------------------------------------------
# Startup diagnostics
# ---------------------------------------------------------------------------

def run_startup_diagnostics(
    config:   "ConfigManager",
    router:   ProviderRouter,
    registry: ToolRegistry | None,
    memory:   MemoryManager | None,
    logger:   logging.Logger,
) -> None:
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
        print(f"\n  Active provider  : {config.get('default_provider','groq').upper()}")
        if len(avail) > 1:
            print(f"  Fallback provider: {config.get('fallback_provider','google').upper()}")
        print(f"  Web UI fallback  : always available")
    else:
        print("\n  ✗  No API providers — Web UI fallback will be used.")

    print("\n  Assistant Online")
    print(sep + "\n")

    failed = [n for n, p in checks.items() if not p]
    if failed:
        logger.warning(f"Startup checks failed: {', '.join(failed)}")
    else:
        logger.info("All startup checks passed")


# ---------------------------------------------------------------------------
# System prompt loaded from vault
# ---------------------------------------------------------------------------
def build_system_prompt(base_prompt: str, memory_context: str) -> str:
    """Combine the vault system prompt with loaded memory context."""
    if memory_context.strip():
        return base_prompt + "\n\n" + memory_context
    return base_prompt

def _fallback_prompt() -> str:
    """Used only when vault is unavailable. Keeps the service functional."""
    return (
        "You are a helpful AI assistant. "
        "Be concise, accurate, and practical. "
        "When you don't know something, say so."
    )

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

READ_TOOLS = {"read_note", "search_vault", "list_vault", "get_linked_notes", "summarise_research"}

VALID_PROVIDERS = ("groq", "google", "webui", "auto")


def handle_vault_command(
    raw:          str,
    registry:     ToolRegistry,
    history:      list[Message],
    memory:       MemoryManager | None,
    logger:       logging.Logger,
    _agent_mode:  bool = False,  # True = called from agent loop, skip duplicate history injection
) -> str | None:
    parts  = raw.split(None, 1)
    prefix = parts[0].lower()

    if prefix not in VAULT_COMMANDS:
        return None

    tool_name, usage = VAULT_COMMANDS[prefix]
    tool_input = parts[1].strip() if len(parts) > 1 else ""

    if not tool_input and tool_name not in ("list_vault",):
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


# ---------------------------------------------------------------------------
# Web handoff terminal helpers
# ---------------------------------------------------------------------------

def _print_handoff_prompt(packaged_prompt: str) -> None:
    sep = "=" * 60
    print(f"\n{sep}")
    print("  WEB HANDOFF — Copy everything between the markers")
    print(f"{sep}\n")
    print(packaged_prompt)
    print(f"\n{sep}")
    print("  END OF PROMPT — Paste into ChatGPT / Claude / Gemini / DeepSeek")
    print(f"{sep}\n")


def _collect_handoff_response() -> str | None:
    print("[Paste the web AI response below, then type '---end' on a new line]\n")
    lines = []
    while True:
        try:
            line = input()
        except (KeyboardInterrupt, EOFError):
            print("\n[Handoff cancelled]\n")
            return None
        if line.strip() == "---end":
            break
        lines.append(line)
    return "\n".join(lines).strip() if lines else None


# ---------------------------------------------------------------------------
# Headless mode — BUG-002
# ---------------------------------------------------------------------------

def _is_headless() -> bool:
    """
    Headless is now the DEFAULT when no terminal flag is given.
    Pass --terminal to force the interactive chat loop.
    The --headless flag is kept for explicitness but is no longer
    needed — any non-TTY environment (systemd, background process)
    also runs headless.
    """
    if "--terminal" in sys.argv:
        return False
    if "--headless" in sys.argv:
        return True
    try:
        return not sys.stdin.isatty()
    except Exception:
        return True


def run_headless(
    watcher_thread:  threading.Thread | None,
    http_server,
    memory,
    router,
    logger:          logging.Logger,
    shutdown_event:  threading.Event,   # NEW parameter
) -> None:
    """
    T7.5.11 fix: block using a polling loop instead of threading.Event().wait().
    Reliably interrupted by KeyboardInterrupt (Ctrl+C) on Windows and Linux.
    Also woken by shutdown_event.set() from the /shutdown HTTP endpoint.
    """
    logger.info("[Headless] Running in headless mode — no terminal input")
    print("[Headless mode active — watcher and HTTP server running]")
    print("[Press Ctrl+C or call GET /shutdown to stop cleanly]\n")

    try:
        # Poll every 0.5s — low CPU, responsive to both Ctrl+C and /shutdown
        while not shutdown_event.is_set():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\n[Headless] Ctrl+C received — shutting down...")
        logger.info("[Headless] KeyboardInterrupt received")

    logger.info("[Headless] Shutdown triggered")

    if http_server:
        http_server.stop()

    if watcher_thread and watcher_thread.is_alive():
        watcher_thread.join(timeout=3)

    if memory:
        memory.close_episode(
            error_summary = router.session_error_summary(),
            tools_used    = [],
        )
        print("[Headless] Episode footer written. Goodbye.\n")
    else:
        print("[Headless] Goodbye.\n")

    logger.info("[Headless] Clean shutdown complete")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    config = ConfigManager()
    logger = setup_logger(config.get("log_level", "INFO"), verbose=False)
    logger.info("Assistant starting — Milestone 8")
    headless = _is_headless()
    mode = "headless" if headless else "terminal"
    logger.info(f"Mode: {mode}")  

    router = ProviderRouter(config.all())

    vault_path = config.get("vault_path", "")
    registry:  ToolRegistry   | None = None
    memory:    MemoryManager  | None = None
    ctx_mgr:   ContextManager | None = None

    if vault_path and Path(vault_path).exists():
        registry = ToolRegistry(vault_path)
        memory   = MemoryManager(vault_path)
        ctx_mgr  = ContextManager(router.registry)
    else:
        logger.warning("Vault path not set or missing — vault tools and memory disabled.")

    memory_context = memory.load_context() if memory else ""
    base_prompt    = memory.load_system_prompt() if memory else _fallback_prompt()
    system_prompt  = build_system_prompt(base_prompt, memory_context)

    if memory:
        memory.seed_webui_prompt() # Seed WebUI-Prompt.md if it doesn't exist
        memory.open_episode()

    run_startup_diagnostics(config, router, registry, memory, logger)

    history:      list[Message]  = []
    history_lock: threading.Lock = threading.Lock()
    shutdown_event: threading.Event = threading.Event()
    tools_used:   list[str]      = []

    # ── Start vault watcher (BUG-003: pass system_prompt) ─────────────────
    watcher:        VaultWatcher | None       = None
    watcher_thread: threading.Thread | None   = None

    if vault_path and Path(vault_path).exists():
        try:
            watcher = VaultWatcher(
                config.all(),
                poll_interval = config.get("watcher_poll_interval", 5),
                system_prompt = system_prompt,   # BUG-003
                registry      = registry,       # ← NEW: enables agent tools in watcher
            )
            watcher_thread = threading.Thread(target=watcher.run, daemon=True)
            watcher_thread.start()
            logger.info("[Main] Vault watcher started")
            print("\n[Vault watcher active in background]\n")
        except Exception as exc:
            logger.error(f"[Main] Failed to start watcher: {exc}")
            print(f"Warning: Watcher failed to start: {exc}\n")
    else:
        logger.warning("[Main] Vault path not available — watcher disabled")

    # ── Start HTTP server ──────────────────────────────────────────────────
    http_server: AssistantServer | None = None

    if vault_path and Path(vault_path).exists():
        try:
            http_server = AssistantServer(
                router        = router,
                memory        = memory,
                registry      = registry,
                history       = history,
                history_lock  = history_lock,
                config        = config.all(),
                system_prompt = system_prompt,
                ep_chat_fn    = ep_chat,
                ep_error_fn   = ep_error,
                ep_handoff_fn = ep_handoff,   # BUG-004
                ep_vault_fn   = ep_vault,
                shutdown_event = shutdown_event,
            )
            http_server.start()
        except Exception as exc:
            logger.error(f"[Main] Failed to start HTTP server: {exc}")
            print(f"Warning: HTTP server failed to start: {exc}\n")
    else:
        logger.warning("[Main] Vault path not available — HTTP server disabled")

    # ── BUG-002: skip chat loop if headless ────────────────────────────────
    if _is_headless():
        run_headless(
            watcher_thread, 
            http_server, 
            memory, 
            router, 
            logger,
            shutdown_event,
        )
        return

    # ── Print help ─────────────────────────────────────────────────────────
    print("Terminal mode active.")
    print("Use --terminal to force terminal mode, or run without a TTY for headless/service mode.")
    print("To force headless/service mode: python assistant.py --headless")
    print()
    print("Vault read   : vault:read | vault:search | vault:list | vault:links")
    print("Vault write  : vault:create | vault:update")
    print("Research     : vault:research | vault:import | vault:summarise")
    print("Memory       : remember: <fact>")
    print("Provider     : /use groq | /use google | /use webui | /use auto")
    print("Info         : tools | models | context | status | verbose on/off")
    print("Session      : clear | exit\n")
    if http_server and http_server.is_available():
        host = config.get("host", "127.0.0.1")
        port = config.get("port", 8765)
        print(f"Obsidian plugin: http://{host}:{port}")
        print(f"API docs       : http://{host}:{port}/docs\n")

    # ── Chat loop ──────────────────────────────────────────────────────────
    provider_override: str | None = None

    while True:
        try:
            user_input = input("You: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nShutting down...")
            break

        if not user_input:
            continue

        if user_input.lower() in ("exit", "quit"):
            print("Shutting down...")
            if watcher:
                watcher.stop()
            if http_server:
                http_server.stop()
            break

        if user_input.lower() == "clear":
            with history_lock:
                history.clear()
            print("[Conversation history cleared — episode log unaffected]\n")
            continue

        if user_input.lower() in ("verbose on", "verbose off"):
            enable = user_input.lower() == "verbose on"
            set_verbose(enable)
            state = "ON — logs appear in console" if enable else "OFF — logs in file only"
            print(f"[Verbose {state}]\n")
            continue

        if user_input.lower().startswith("/use "):
            target = user_input[5:].strip().lower()
            if target not in VALID_PROVIDERS:
                print(f"[Unknown provider '{target}'. Options: {', '.join(VALID_PROVIDERS)}]\n")
            elif target == "auto":
                provider_override = None
                print("[Provider: AUTO — smart routing active]\n")
            else:
                provider_override = target
                print(f"[Provider override: {target.upper()}]\n")
            continue

        if user_input.lower() == "status":
            print("\n--- Status ---")
            for name, avail in router.status().items():
                print(f"  {'✓' if avail else '✗'}  {name.capitalize()}")
            print(f"  Provider mode: {provider_override.upper() if provider_override else 'AUTO'}")
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

        if user_input.lower() == "models":
            print(router.capability_report())
            continue

        if user_input.lower() == "context":
            if ctx_mgr and router.available_providers:
                active = router.available_providers[0]
                print(f"\n  {ctx_mgr.report(history, active, system_prompt)}")
                print(f"  System prompt  : ~{estimate_tokens([], system_prompt)} tokens")
                print(f"  History entries: {len(history)}\n")
            else:
                print("[Context manager not available]\n")
            continue

        if user_input.lower() == "tools":
            if registry is None:
                print("[Vault tools not available — set vault_path in settings.json]\n")
            else:
                print("\n--- Available Tools ---")
                for t in registry.list_tools():
                    print(f"  {t['name']:<22} {t['description']}")
                print("----------------------\n")
            continue

        if user_input.lower().startswith("remember:"):
            fact = user_input[len("remember:"):].strip()
            if memory:
                result = memory.remember(fact)
                memory.append_episode(ep_remember(fact))
                print(f"\n{result}\n")
            else:
                print("[Memory not available — vault path not set]\n")
            continue

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

        # ── Normal AI chat — agent loop ───────────────────────────────────
        logger.info(f"User: {user_input[:80]}{'...' if len(user_input) > 80 else ''}")

        try:
             agent_ctx = AgentContext(
                 user_input        = user_input,
                 history           = history,
                 history_lock      = history_lock,
                 router            = router,
                 registry          = registry,
                 memory            = memory,
                 ctx_mgr           = ctx_mgr,
                 system_prompt     = system_prompt,
                 max_tokens        = config.get("max_tokens", 2048),
                 temperature       = config.get("temperature", 0.7),
                 provider_override = provider_override,
                 ep_vault_fn       = ep_vault,
                 ep_error_fn       = ep_error,
                 tools_used        = tools_used,
             )
             reply, used_provider = run_agent_loop(agent_ctx)

        except ProviderWebUIHandoff as handoff:
            with history_lock:
                if history and history[-1].role == "user":
                    history.pop()

            _print_handoff_prompt(handoff.packaged_prompt)
            if memory:
                memory.append_episode(ep_handoff("sent", user_input[:80]))   # BUG-004

            pasted = _collect_handoff_response()
            if pasted:
                with history_lock:
                    history.append(Message(role="user",      content=user_input))
                    history.append(Message(role="assistant", content=pasted))
                print(f"\nAssistant [web]: {pasted}\n")
                if memory:
                    memory.append_episode(ep_chat(user_input, pasted, provider="web"))
                    memory.append_episode(ep_handoff("returned", f"{len(pasted)} chars"))   # BUG-004
            else:
                print("[Handoff cancelled — message not added to history]\n")
            continue

        except ProviderError as exc:
            print(f"\n[Error] {exc}\n")
            logger.error(f"Provider error: {exc}")
            with history_lock:
                if history and history[-1].role == "user":
                    history.pop()
            if memory:
                memory.append_episode(ep_error(str(exc)[:120]))
            continue

        logger.info(f"Assistant replied via {used_provider} ({len(reply)} chars)")
        print(f"\nAssistant [{used_provider}]: {reply}\n")

        if memory:
            memory.append_episode(ep_chat(user_input, reply, provider=used_provider))

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------
    logger.info("Assistant shutting down.")

    if watcher_thread and watcher_thread.is_alive():
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

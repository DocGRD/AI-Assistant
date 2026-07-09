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
from pathlib import Path

logger = logging.getLogger("assistant")

# BUG-008: detect missing venv early with a clear user-facing message.
# These are the packages the live runtime actually needs: the generic
# OpenAI-compatible adapter (`openai`) and the HTTP server (`fastapi`).
# (The old groq / google-genai SDK checks were stale — those SDKs are no
#  longer used now that every provider routes through one REST adapter.)
def _check_venv() -> None:
    missing = []
    try:
        import openai  # noqa: F401
    except ImportError:
        missing.append("openai")
    try:
        import fastapi  # noqa: F401
    except ImportError:
        missing.append("fastapi")

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

from assistant_core.server import AssistantServer

from assistant_core.paths import REPO_ROOT, LOGS_DIR, CONFIG_DIR
from assistant_core.config.config_manager import ConfigManager
from assistant_core.config.logger import setup_logger, set_verbose, is_verbose
from assistant_core.providers.provider_router import ProviderRouter
from assistant_core.providers.base_provider import Message, ProviderError, ProviderWebUIHandoff
from assistant_core.providers.model_registry import estimate_tokens
from assistant_core.memory.memory_manager import MemoryManager
from assistant_core.memory.context_manager import ContextManager
from assistant_core.tools.tool_registry import ToolRegistry
from assistant_core.watcher.vault_watcher import VaultWatcher
from assistant_core.agent_loop import AgentContext, run_agent_loop
from assistant_core.episodes import ep_vault, ep_remember, ep_chat, ep_error, ep_handoff
from assistant_core.diagnostics import run_startup_diagnostics, build_system_prompt, fallback_prompt, is_vault
from assistant_core.vault_commands import (
    VAULT_COMMANDS, READ_TOOLS, NO_INPUT_OK, VALID_PROVIDERS, handle_vault_command,
)


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
    vault_ok   = is_vault(vault_path)   # exists, is a dir, AND has .obsidian/ (T3.20)
    registry:  ToolRegistry   | None = None
    memory:    MemoryManager  | None = None
    ctx_mgr:   ContextManager | None = None

    if vault_ok:
        registry = ToolRegistry(vault_path, config.all(), router=router)
        memory   = MemoryManager(vault_path)
        ctx_mgr  = ContextManager(router.registry, router=router, config=config.all())
    elif vault_path and Path(vault_path).exists():
        logger.warning(f"vault_path '{vault_path}' exists but is not an Obsidian vault "
                       "(no .obsidian/ folder) — vault tools and memory disabled. "
                       "Point it at a real vault, or open it in Obsidian first.")
    else:
        logger.warning("Vault path not set or missing — vault tools and memory disabled.")

    memory_context = memory.load_context() if memory else ""
    base_prompt    = memory.load_system_prompt() if memory else fallback_prompt()
    system_prompt  = build_system_prompt(base_prompt, memory_context)

    if memory:
        memory.seed_webui_prompt() # Seed WebUI-Prompt.md if it doesn't exist
        memory.seed_prompts()      # M13 — seed AI/Prompts/ examples if empty
        memory.seed_scripts()      # M15 — seed AI/Scripts/ README (propose/commit)
        memory.seed_help()         # v1.7 — self-updating, indexed AI/Help knowledge base
        memory.open_episode()

    # ── M11 Vault QA (RAG) — one shared index. Only the enabled machine indexes. ──
    from assistant_core.rag.service import RagService
    rag_service: "RagService | None" = RagService(config.all()) if vault_ok else None

    # ── M17 — one-shot consolidation ("dreaming"). Runs and exits. ────────
    if "--consolidate" in sys.argv:
        if not vault_ok:
            print("[Consolidation] No vault configured — nothing to do."); return
        from assistant_core.consolidation import ConsolidationEngine
        apply = "--apply" in sys.argv
        embedder = rag_service.embedder if (rag_service and rag_service.enabled) else None
        archive_days = int(config.get("episode_archive_days", 30))
        report = ConsolidationEngine(vault_path, router, embedder).run(
            apply=apply, archive_days=archive_days)
        print(f"[Consolidation] days={report['days']} new={len(report['new_facts'])} "
              f"dups={len(report['duplicates'])} applied={report['applied']} "
              f"archived={len(report['archived'])} proposal={report['proposal']}")
        if memory:
            memory.append_episode(ep_vault(
                "consolidate",
                f"{len(report['new_facts'])} new fact(s), applied={report['applied']}"))
            memory.close_episode()
        return

    # ── M18 — one-shot / nightly knowledge-graph build. Runs and exits. ───
    if "--build-graph" in sys.argv:
        if not vault_ok:
            print("[Graph] No vault configured — nothing to do."); return
        from assistant_core.graph.job import build_graph
        limit = config.get("graph_build_limit", 50)
        for i, a in enumerate(sys.argv):
            if a == "--limit" and i + 1 < len(sys.argv):
                try: limit = int(sys.argv[i + 1])
                except ValueError: pass
        rep = build_graph(vault_path, router, limit=int(limit))
        print(f"[Graph] processed {len(rep['processed'])} note(s); "
              f"+{rep['relations']} relation(s), {rep['entities']} entity touch(es).")
        if memory:
            memory.append_episode(ep_vault("build_graph", f"{len(rep['processed'])} notes"))
            memory.close_episode()
        return

    run_startup_diagnostics(config, router, registry, memory, logger)

    if rag_service:
        if rag_service.enabled:
            print("[Vault QA] Building/refreshing the index (this machine indexes)...")
            try:
                rep = rag_service.reindex()
                print(f"[Vault QA] Index ready: {rep} | {rag_service.stats()}\n")
            except Exception as exc:
                logger.error(f"[Vault QA] Startup index failed: {exc}")
                print(f"[Vault QA] Startup index failed: {exc}\n")
        else:
            print(f"[Vault QA] Index: {rag_service.stats()} — indexing OFF on this machine "
                  f"(set index_on_startup: true on the indexing host)\n")

    history:      list[Message]  = []
    history_lock: threading.Lock = threading.Lock()
    shutdown_event: threading.Event = threading.Event()
    tools_used:   list[str]      = []

    # ── Start vault watcher (BUG-003: pass system_prompt) ─────────────────
    watcher:        VaultWatcher | None       = None
    watcher_thread: threading.Thread | None   = None

    if vault_ok:
        try:
            watcher = VaultWatcher(
                config.all(),
                poll_interval = config.get("watcher_poll_interval", 5),
                system_prompt = system_prompt,   # BUG-003
                registry      = registry,       # ← NEW: enables agent tools in watcher
                rag           = rag_service,    # M11: incremental re-index on change (if enabled)
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

    # ── Start background maintenance scheduler (M16.7 discovery + M17 dreaming) ──
    maintenance_scheduler = None
    if vault_ok:
        try:
            from assistant_core.scheduler import MaintenanceScheduler
            maintenance_scheduler = MaintenanceScheduler(vault_path, config.all(),
                                                         router=router, rag=rag_service)
            maintenance_scheduler.start()
        except Exception as exc:
            logger.error(f"[Main] Failed to start maintenance scheduler: {exc}")

    # ── Start HTTP server ──────────────────────────────────────────────────
    http_server: AssistantServer | None = None

    if vault_ok:
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
                rag           = rag_service,   # M11: Vault QA mode
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
    print("Vault read   : vault:read | vault:search | vault:list | vault:find <glob> | vault:links")
    print("Vault write  : vault:create | vault:update")
    print("Research     : vault:research | vault:import | vault:summarise")
    print("Memory       : remember: <fact>")
    print("Provider     : /use groq | /use google | /use cerebras | /use webui | /use auto")
    print("Privacy      : private on/off  |  allow-webui on/off  (private routes only to no-train providers)")
    print("Providers    : vault:update-providers [provider|apply]  |  vault:models (live discovery)")
    print("Info         : tools | models | context | status | verbose on/off")
    print("Session      : clear | exit\n")
    if http_server and http_server.is_available():
        host = config.get("host", "127.0.0.1")
        port = config.get("port", 8765)
        print(f"Obsidian plugin: http://{host}:{port}")
        print(f"API docs       : http://{host}:{port}/docs\n")

    # ── Chat loop ──────────────────────────────────────────────────────────
    provider_override: str | None = None
    private_mode:        bool = False   # M10 — route only to trains_on_data=no providers
    allow_webui_private: bool = False   # M10 — permit WebUI handoff while private

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

        if user_input.lower() in ("private on", "private off"):
            private_mode = user_input.lower() == "private on"
            if private_mode:
                print("[Private ON — routing only to providers that do NOT train on data "
                      "(Google excluded). WebUI handoff disabled unless 'allow-webui on'.]\n")
            else:
                print("[Private OFF — normal routing.]\n")
            continue

        if user_input.lower() in ("allow-webui on", "allow-webui off"):
            allow_webui_private = user_input.lower() == "allow-webui on"
            state = "ON — WebUI handoff permitted for private turns" if allow_webui_private \
                else "OFF — WebUI handoff blocked for private turns"
            print(f"[Allow-WebUI {state}]\n")
            continue

        if user_input.lower().startswith("/use "):
            target = user_input[5:].strip().lower()
            valid = set(VALID_PROVIDERS) | set(router.available_models)
            if target not in valid:
                print(f"[Unknown provider '{target}'. Options: {', '.join(sorted(valid))}]\n")
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
            print(f"  Private mode : {'ON' if private_mode else 'OFF'}"
                  f"{'  (allow-webui ON)' if allow_webui_private else ''}")
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

        if user_input.lower().startswith("vault:reindex"):
            if not rag_service:
                print("[Vault QA unavailable — set vault_path in settings.json]\n")
                continue
            do_full = "full" in user_input.lower().split()[1:]
            print("[Vault QA] Indexing — first run downloads the embedding model (~130 MB), then offline...")
            try:
                report = rag_service.reindex(full=do_full)
                print(f"[Vault QA] Reindex complete: {report} | index now holds {rag_service.stats()}\n")
            except Exception as exc:
                logger.error(f"[Vault QA] Reindex failed: {exc}")
                print(f"[Vault QA] Reindex failed: {exc}\n")
            continue

        if user_input.lower().startswith("vault:ask"):
            question = user_input[len("vault:ask"):].strip()
            if not question:
                print("Usage: vault:ask <question>\n")
                continue
            if not rag_service:
                print("[Vault QA unavailable — set vault_path in settings.json]\n")
                continue
            if not rag_service.has_index():
                print("[Vault QA] No index on this machine — build it where the service runs "
                      "(vault:reindex on the server).\n")
                continue
            from assistant_core.rag.qa import run_vault_qa
            try:
                res = run_vault_qa(
                    router, rag_service.retriever(), question,
                    force_private=private_mode,
                    max_tokens=config.get("max_tokens", 2048),
                    temperature=config.get("temperature", 0.3),
                )
            except ProviderError as exc:
                print(f"\n[Vault QA] {exc}\n")
                continue
            if not res["answer"]:
                print("[Vault QA] No relevant notes found for that question.\n")
                continue
            tag = f"{res['provider']}{' · private' if res['private'] else ''}"
            print(f"\nVault QA [{tag}]: {res['answer']}")
            kinds = res.get("source_kinds") or []
            srcs  = [s + (" (graph)" if i < len(kinds) and kinds[i] == "graph" else "")
                     for i, s in enumerate(res["sources"])]
            print(f"Sources: {', '.join(srcs)}\n")
            if memory:
                memory.append_episode(ep_chat(f"[vault:ask] {question}", res["answer"], provider=res["provider"]))
            continue

        if user_input.lower() == "vault:discover-providers":
            # M16.7 — build a PROPOSED registry from each provider's /models, written for
            # review. `vault:update-providers apply` commits. Shares the same job the
            # weekly scheduler runs (assistant_core.providers.discovery_job).
            if not vault_ok:
                print("[Discovery] Set a valid vault_path first.\n"); continue
            from assistant_core.providers.discovery_job import run_discovery_proposal
            print("[Discovery] Querying /models for each provider...")
            ok, msg = run_discovery_proposal(vault_path, config.all())
            print(f"[Discovery] {msg}. Review it, then `vault:update-providers apply` to commit.\n"
                  if ok else f"[Discovery] {msg}.\n")
            if ok and memory:
                memory.append_episode(ep_vault("discover_providers", msg))
            continue

        if user_input.lower() == "vault:models":
            # Ask each provider's own /models endpoint what THIS account can use
            # (authoritative — not a curated list). Flags registry rows that are stale.
            from assistant_core.providers.model_discovery import discover_models
            from assistant_core.providers.registry_loader import RegistryLoader
            reg_path = (Path(vault_path) / "AI" / "System" / "Provider-Registry.md") if vault_ok else None
            specs = RegistryLoader(reg_path).load() if (reg_path and reg_path.exists()) else []
            providers = {}
            known: dict[str, set] = {}
            for s in specs:
                providers.setdefault(s.provider, s.base_url)
                known.setdefault(s.provider, set()).add(s.model_id)
            if not providers:
                print("[Discovery] No registry providers found (set a valid vault_path).\n")
                continue
            print("[Discovery] Querying each provider's /models endpoint with your keys...\n")
            for prov, r in discover_models(providers, config.all()).items():
                if r["error"]:
                    print(f"  {prov:10} ✗ {r['error']}")
                    continue
                avail = set(r["models"])
                print(f"  {prov:10} {len(avail)} model(s) available:")
                for m in r["models"]:
                    print(f"      {'★' if m in known.get(prov, set()) else ' '} {m}")
                stale = known.get(prov, set()) - avail
                if stale:
                    print(f"    ⚠ in registry but NOT available to you: {', '.join(sorted(stale))}")
            print("\n  ★ = already in your Provider-Registry.md\n")
            continue

        if user_input.lower() == "vault:test":
            import os as _os, subprocess as _sp
            mods = ["tests.test_rag", "tests.test_chat_context", "tests.test_editing",
                    "tests.test_routing", "tests.test_registry_loader", "tests.test_memory",
                    "tests.test_scripts_runner", "tests.test_agent_loop", "tests.test_diagnostics",
                    "tests.test_model_discovery", "tests.test_memory_episodes", "tests.test_research",
                    "tests.test_watcher", "tests.test_server_endpoints", "tests.test_handoff",
                    "tests.test_find_notes", "tests.test_registry_proposer",
                    "tests.test_vault_fileops", "tests.test_task_ledger",
                    "tests.test_scheduler", "tests.test_research_roundtrip",
                    "tests.test_consolidation", "tests.test_excalidraw", "tests.test_ocr",
                    "tests.test_graph", "tests.test_web", "tests.test_search_vault",
                    "tests.test_ingest", "tests.test_scripture", "tests.test_query",
                    "tests.test_audio", "tests.test_study", "tests.test_provenance"]
            print("[Self-test] Running the unittest suite...")
            env = {**_os.environ, "PYTHONIOENCODING": "utf-8"}
            proc = _sp.run([sys.executable, "-m", "unittest", *mods],
                           cwd=str(REPO_ROOT), capture_output=True, text=True, env=env)
            tail = "\n".join((proc.stderr or "").strip().splitlines()[-6:])
            print(tail)
            passed = proc.returncode == 0
            print(f"[Self-test] {'PASSED' if passed else 'FAILED'}\n")
            if memory:
                memory.append_episode(ep_vault("self_test", "PASSED" if passed else "FAILED"))
            continue

        if user_input.lower().startswith("vault:run-script"):
            name = user_input[len("vault:run-script"):].strip()
            if not name:
                print("Usage: vault:run-script <name>   (runs an approved AI/Scripts/<name>.py)\n")
                continue
            if not vault_ok:
                print("[Scripts unavailable — set vault_path in settings.json]\n")
                continue
            from assistant_core.scripts_runner import run_vault_script
            ok, out = run_vault_script(vault_path, name)
            print(f"\n[Script {name}] {'✓' if ok else '✗'}\n{out}\n")
            if memory:
                memory.append_episode(ep_vault("run_script", f"{name} {'ok' if ok else 'fail'}"))
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

            # M25 — vault:sources <claim>: provenance audit.
            if user_input.lower().startswith("vault:sources"):
                claim = user_input[len("vault:sources"):].strip()
                if not claim:
                    print("Usage: vault:sources <claim>\n"); continue
                from assistant_core.provenance import find_sources
                rep = find_sources(vault_path, claim)
                if not rep["sources"]:
                    print("[Sources] ⚠ Unsourced — no notes contain these terms.\n")
                else:
                    print(("[Sources] " + ("" if rep["sourced"] else "⚠ weakly sourced — ")) +
                          "\n".join(f"  {s['path']} ({s['matched']}/{s['of']})" for s in rep["sources"]) + "\n")
                continue

            # M28 — vault:cards <note> / vault:review.
            if user_input.lower().startswith("vault:cards"):
                note = user_input[len("vault:cards"):].strip()
                if not note:
                    print("Usage: vault:cards <note>\n"); continue
                from assistant_core.study.cards import generate_cards, add_cards
                res = registry.run("read_note", note)
                if not res.success:
                    print(f"[Cards] could not read {note}\n"); continue
                cards = generate_cards(router, res.output)
                added = add_cards(vault_path, cards, (res.metadata or {}).get("path", note))
                print(f"[Cards] added {added} card(s) from {note} (of {len(cards)} generated)\n")
                if memory:
                    memory.append_episode(ep_vault("cards", f"{note}: {added}"))
                continue

            if user_input.lower().strip() == "vault:review":
                from assistant_core.study.cards import due_cards
                due = due_cards(vault_path)
                if not due:
                    print("[Review] no cards due. 🎉\n")
                else:
                    print(f"[Review] {len(due)} due:\n" +
                          "\n".join(f"  Q: {c['q']}\n  A: {c['a']}" for c in due[:10]) + "\n")
                continue

            # M26 — vault:query <expr>: structured/exact search.
            if user_input.lower().startswith("vault:query"):
                expr = user_input[len("vault:query"):].strip()
                if not expr:
                    print('Usage: vault:query tag:sermon "the last hour" path:"06 - Projects"\n'); continue
                from assistant_core.query import structured_search
                hits = structured_search(vault_path, expr)
                if not hits:
                    print(f"[Query] no notes match: {expr}\n")
                else:
                    print(f"[Query] {len(hits)} note(s):\n" + "\n".join(f"  {h['path']}" for h in hits) + "\n")
                continue

            # M24 — vault:passage <ref>: cited overview of a Bible passage from your notes.
            if user_input.lower().startswith("vault:passage"):
                ref = user_input[len("vault:passage"):].strip()
                if not ref:
                    print("Usage: vault:passage <e.g. 1 John 2:18-20>\n"); continue
                from assistant_core.scripture.passage import build_passage_guide
                print(f"[Passage] gathering notes for {ref} ...")
                rep = build_passage_guide(vault_path, router, ref, rag=rag_service)
                if rep.get("error"):
                    print(f"[Passage] {rep['error']}\n")
                else:
                    print(f"\n**Passage: {rep['ref']}**\n\n{rep['guide']}\n")
                    if rep["notes"]:
                        print(f"*Notes: {', '.join(rep['notes'][:8])}*\n")
                if not rep.get("error") and memory:
                    memory.append_episode(ep_vault("passage", ref[:80]))
                continue

            # M22 — vault:ingest <file>: extract a PDF/EPUB/DOCX/txt into AI/Library (indexed).
            if user_input.lower().startswith("vault:ingest"):
                src = user_input[len("vault:ingest"):].strip()
                if not src:
                    print("Usage: vault:ingest <path to document>\n"); continue
                from assistant_core.ingest.ingest import ingest_file
                print(f"[Ingest] extracting {src} ...")
                rep = ingest_file(vault_path, src, config.all(), rag=rag_service, router=router)
                if rep.get("error"):
                    print(f"[Ingest] {rep['error']}\n")
                else:
                    print(f"[Ingest] {rep['format']} — {rep['pages']} page(s), {rep['chars']} chars → "
                          f"{rep['note_path']}\n")
                if not rep.get("error") and memory:
                    memory.append_episode(ep_vault("ingest", f"{src} → {rep['note_path']}"))
                continue

            # M27 — vault:transcribe <audio>: local transcription → AI/Derived sidecar.
            if user_input.lower().startswith("vault:transcribe"):
                aud = user_input[len("vault:transcribe"):].strip()
                if not aud:
                    print("Usage: vault:transcribe <audio path>\n"); continue
                from assistant_core.media.audio import transcribe_to_sidecar
                print(f"[Transcribe] {aud} (local Whisper) ...")
                rep = transcribe_to_sidecar(vault_path, aud, config.all(), rag=rag_service)
                print(f"[Transcribe] {rep['error']}\n" if rep.get("error")
                      else f"[Transcribe] {rep['chars']} chars → {rep['sidecar']}\n")
                if not rep.get("error") and memory:
                    memory.append_episode(ep_vault("transcribe", aud[:80]))
                continue

            # paperclip — vault:analyze <image>: transcribe + describe one image.
            if user_input.lower().startswith("vault:analyze"):
                img = user_input[len("vault:analyze"):].strip()
                if not img:
                    print("Usage: vault:analyze <image path>\n"); continue
                from assistant_core.media.ocr import analyze_image
                print(f"[Analyze] reading {img} ...")
                text, err = analyze_image(vault_path, img, router, config.all(), private=private_mode)
                print(f"[Analyze] {err}\n" if err else f"\nImage: {img}\n\n{text}\n")
                if not err and memory:
                    memory.append_episode(ep_vault("analyze", img[:80]))
                continue

            # M19 — vault:ocr <note>: extract text from the note's images into an
            # AI/Derived sidecar (vision model, tesseract fallback; privacy-aware).
            if user_input.lower().startswith("vault:ocr"):
                target = user_input[len("vault:ocr"):].strip()
                if not target:
                    print("Usage: vault:ocr <note path>\n"); continue
                from assistant_core.media.ocr import OcrEngine, make_vision_fn
                engine = OcrEngine(vault_path, vision_fn=make_vision_fn(router, config.all()))
                print(f"[OCR] Processing images in {target} ...")
                rep = engine.ocr_note(target, private=private_mode)
                if rep.get("error"):
                    print(f"[OCR] {rep['error']}\n")
                else:
                    print(f"[OCR] {rep['ocred']}/{rep['images']} image(s) read "
                          f"({', '.join(sorted(set(rep['engine']))) or 'none'}); "
                          f"sidecar: {rep['sidecar']}\n")
                    if rep["sidecar"] and rag_service and rag_service.enabled:
                        try: rag_service.maybe_index_note(rep["sidecar"],
                                                          (Path(vault_path) / rep["sidecar"]).read_text(encoding="utf-8"))
                        except Exception: pass
                if memory:
                    memory.append_episode(ep_vault("ocr", f"{target} → {rep.get('sidecar')}"))
                continue

            # M5/T5.10 — vault:summarise/summarize: load the note (robust path resolution)
            # then produce the bullet summary in one non-agentic call.
            if user_input.lower().startswith(("vault:summarise", "vault:summarize")):
                path_arg = user_input[len("vault:summarise"):].strip()   # both spellings are 15 chars
                res = registry.run("summarise_research", path_arg)
                if not res.success:
                    print(f"\n✗ [summarise_research]\n\n{res.output}\n"); continue
                print(f"\n✓ [summarise_research] loaded {path_arg}\n")
                from assistant_core.providers.base_provider import Message
                try:
                    reply, prov = router.generate(
                        messages=[Message(role="user", content=res.output)],
                        system_prompt=("Summarise the research note above as concise bullet points "
                                       "under Key Facts, Practical Applications, and Project "
                                       "Implications. Output only the summary."),
                        max_tokens=600, temperature=0.3, private=private_mode)
                    print(f"Assistant [{prov}]: {reply}\n")
                except Exception as exc:
                    print(f"[summary failed: {exc}]\n")
                if memory:
                    memory.append_episode(ep_vault("summarise_research", path_arg[:80]))
                continue

            # M21 — vault:webresearch <query>: autonomous web research (search + fetch +
            # synthesise + save with citations). Blocked for private turns.
            if user_input.lower().startswith("vault:webresearch"):
                q = user_input[len("vault:webresearch"):].strip()
                if not q:
                    print("Usage: vault:webresearch <question>\n"); continue
                from assistant_core.web.research import run_web_research
                print(f"[Web] searching + fetching for: {q} ...")
                rep = run_web_research(q, router, config.all(), rag=rag_service, private=private_mode)
                if rep.get("error"):
                    print(f"[Web] {rep['error']}\n")
                else:
                    print(f"[Web] saved {rep['summary_path']} — {len(rep['sources'])} source(s)"
                          + (f", {len(rep['related'])} related note(s)" if rep['related'] else "") + "\n")
                if memory:
                    memory.append_episode(ep_vault("webresearch", q[:80]))
                continue

            # M18 — vault:guide <topic>: assemble a cited guide from the knowledge graph.
            if user_input.lower().startswith("vault:guide"):
                topic = user_input[len("vault:guide"):].strip()
                if not topic:
                    print("Usage: vault:guide <topic>\n"); continue
                from assistant_core.graph.guide import build_guide
                print(f"[Guide] assembling for: {topic} ...")
                rep = build_guide(vault_path, router, topic, rag=rag_service,
                                  include_private=bool(config.get("graph_include_private", False)))
                if rep.get("error"):
                    print(f"[Guide] {rep['error']}\n")
                else:
                    print(f"\n**Guide: {rep['entity']}**\n\n{rep['guide']}\n")
                    if rep["sources"]:
                        print(f"*Sources: {', '.join(rep['sources'][:8])}*\n")
                if memory:
                    memory.append_episode(ep_vault("guide", topic[:80]))
                continue

            # M18 — vault:graph-merge <canonical> -> <alias>: merge two graph entities.
            if user_input.lower().startswith("vault:graph-merge"):
                arg = user_input[len("vault:graph-merge"):].strip()
                sep = "->" if "->" in arg else ("=>" if "=>" in arg else None)
                if not sep:
                    print("Usage: vault:graph-merge <canonical> -> <alias>\n"); continue
                from assistant_core.graph.store import merge_entities
                canon, alias = (p.strip() for p in arg.split(sep, 1))
                ok = merge_entities(vault_path, canon, alias)
                print(f"[Graph] {'merged ' + alias + ' -> ' + canon if ok else 'merge failed (check entities)'}\n")
                continue

            # M18 — vault:graph <note>: extract entities/relations into AI/Graph/Entities.
            if user_input.lower().startswith("vault:graph"):
                target = user_input[len("vault:graph"):].strip()
                if not target:
                    print("Usage: vault:graph <note path>\n"); continue
                from assistant_core.graph.job import build_graph_for_note
                print(f"[Graph] Extracting relationships from {target} ...")
                rep = build_graph_for_note(vault_path, router, target)
                if rep.get("error"):
                    print(f"[Graph] {rep['error']}\n")
                else:
                    print(f"[Graph] {rep['triples']} relationship(s); +{rep.get('relations', 0)} new, "
                          f"{rep.get('entities', 0)} entities touched (AI/Graph/Entities/).\n")
                if memory:
                    memory.append_episode(ep_vault("graph", f"{target}: {rep.get('triples', 0)}"))
                continue

            # M20 — vault:research auto-enters paste-back mode (terminal parity with the
            # plugin's Submit Response): print the prompt, wait for the pasted web-AI
            # research, then save it verbatim + synthesise via the shared round-trip.
            if user_input.lower().startswith("vault:research"):
                q = user_input[len("vault:research"):].strip()
                output = handle_vault_command(user_input, registry, history, memory, logger)
                if output is not None:
                    tools_used.append("vault:research")
                    print(f"\n{output}\n")
                print("[Paste the web AI's research below, then type '---end' on a new "
                      "line — or just '---end' to skip]\n")
                pasted_lines = []
                while True:
                    try:
                        line = input()
                    except (KeyboardInterrupt, EOFError):
                        break
                    if line.strip() == "---end":
                        break
                    pasted_lines.append(line)
                if pasted_lines:
                    from assistant_core.research_roundtrip import (
                        save_research_verbatim, summarize_research, append_related_notes,
                    )
                    research_text = "\n".join(pasted_lines)
                    saved = save_research_verbatim(registry, research_text)
                    if saved:
                        print(f"\n✓ Research saved verbatim: {saved}\n")
                    summary = summarize_research(router, q, research_text, private=private_mode)
                    related = append_related_notes(rag_service, vault_path, saved)
                    print(f"\nAssistant [research]: {summary or '(saved; no summary available)'}\n")
                    if related:
                        print(f"[Linked {len(related)} related note(s) from your vault.]\n")
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
                 private                = private_mode,
                 allow_webui_on_private = allow_webui_private,
                 max_steps              = config.get("max_agent_steps", 10),
                 config                 = config.all(),
                 rag                    = rag_service,
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
            if private_mode and not allow_webui_private:
                print("[This turn was PRIVATE — only no-train providers were tried and the WebUI "
                      "handoff was disabled. To permit a WebUI handoff (exposes content to a web AI), "
                      "type 'allow-webui on' and resend.]\n")
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

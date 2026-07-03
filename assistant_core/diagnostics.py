"""Startup diagnostics and system-prompt assembly.

Pulled out of `app.py` so the bootstrap path stays readable. Uses duck typing
(no heavy imports) — the router/registry/memory are only type hints — so this
module is cheap to import.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from assistant_core.paths import CONFIG_DIR, LOGS_DIR, is_vault  # is_vault re-exported for callers/tests

if TYPE_CHECKING:
    from assistant_core.config.config_manager import ConfigManager
    from assistant_core.providers.provider_router import ProviderRouter
    from assistant_core.tools.tool_registry import ToolRegistry
    from assistant_core.memory.memory_manager import MemoryManager


def run_startup_diagnostics(
    config:   "ConfigManager",
    router:   "ProviderRouter",
    registry: "ToolRegistry | None",
    memory:   "MemoryManager | None",
    logger:   logging.Logger,
) -> None:
    checks: dict[str, bool] = {}

    checks["Config Loaded"] = (CONFIG_DIR / "settings.json").exists()

    vault_path = config.get("vault_path", "")
    checks["Vault Found"] = is_vault(vault_path)

    LOGS_DIR.mkdir(exist_ok=True)
    checks["Logs Ready"] = LOGS_DIR.exists()

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

    # Clear, actionable reason when the vault is unavailable (logs go to file only).
    if not checks["Vault Found"]:
        print("\n  ⚠  VAULT UNAVAILABLE — vault tools, memory, Vault QA, and the registry")
        print("     file are disabled (running on hardcoded provider fallbacks).")
        if not vault_path:
            print("     Reason: no \"vault_path\" is set.")
        elif not Path(vault_path).exists():
            print(f"     Reason: path not found — '{vault_path}'")
        else:
            print(f"     Reason: '{vault_path}' is not an Obsidian vault (no .obsidian/ folder).")
        print("     Fix: set \"vault_path\" in assistant_core/config/settings.json to your")
        print("     Obsidian vault folder (the one with a .obsidian/ directory), then restart.")
        print(sep)

    avail = router.available_providers
    if avail:
        print(f"\n  Active provider  : {config.get('default_provider','groq').upper()}")
        if len(avail) > 1:
            print(f"  Fallback provider: {config.get('fallback_provider','google').upper()}")
        print(f"  Web UI fallback  : always available")
    else:
        print("\n  ✗  No API providers — Web UI fallback will be used.")

    # M10 — live provider registry table (active vs candidate, health, ≥3 floor warning)
    print(router.startup_report())

    print("\n  Assistant Online")
    print(sep + "\n")

    failed = [n for n, p in checks.items() if not p]
    if failed:
        logger.warning(f"Startup checks failed: {', '.join(failed)}")
    else:
        logger.info("All startup checks passed")


def build_system_prompt(base_prompt: str, memory_context: str) -> str:
    """Combine the vault system prompt with loaded memory context."""
    if memory_context.strip():
        return base_prompt + "\n\n" + memory_context
    return base_prompt


def fallback_prompt() -> str:
    """Used only when the vault is unavailable. Keeps the service functional."""
    return (
        "You are a helpful AI assistant. "
        "Be concise, accurate, and practical. "
        "When you don't know something, say so."
    )

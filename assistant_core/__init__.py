"""assistant_core — the zero-cost AI assistant service for Obsidian.

Entry points:
    python -m assistant_core      # headless by default; --terminal for the chat loop
    python assistant.py           # back-compat shim at the repo root

Submodules: app (orchestration + terminal loop), server (HTTP API), agent_loop,
editing, scripts_runner, plus the config / providers / memory / tools / watcher /
rag packages. Filesystem anchors live in `assistant_core.paths`.
"""

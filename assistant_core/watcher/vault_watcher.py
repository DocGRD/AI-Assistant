"""
Vault Watcher — refactor: passes registry to RequestHandler

Changes:
  - __init__() now accepts registry parameter (ToolRegistry | None).
  - Passes registry to RequestHandler so the agent loop inside it
    can execute vault commands autonomously.
  - system_prompt and TOCTOU (content=content) fixes preserved.
"""

import logging
import time
from pathlib import Path
from datetime import datetime

from assistant_core.config.config_manager import ConfigManager
from assistant_core.config.logger import setup_logger
from assistant_core.providers.provider_router import ProviderRouter
from assistant_core.watcher.frontmatter_parser import FrontmatterParser
from assistant_core.watcher.request_handler import RequestHandler

logger = logging.getLogger("watcher")


class VaultWatcher:

    def __init__(
        self,
        config:        dict,
        poll_interval: int  = 5,
        system_prompt: str  = "",
        registry             = None,   # ToolRegistry | None  ← NEW
        rag                  = None,   # RagService | None — M11 incremental indexing
    ):
        self._vault_path    = config.get("vault_path", "")
        self._vault         = Path(self._vault_path)
        self._poll_interval = poll_interval
        self._last_check:   dict[str, float] = {}
        self._running       = False
        self._rag           = rag
        # Throttle incremental re-indexing so a mass change can't block the HTTP event loop:
        # at most `reindex_cap` notes per poll pass, with a short yield between each.
        self._reindex_cap      = int(config.get("watcher_reindex_cap", 40))
        self._reindex_throttle = float(config.get("watcher_reindex_throttle", 0.05))
        self._reindexed_this_pass = 0

        if not self._vault.exists():
            raise ValueError(f"Vault path does not exist: {self._vault_path}")

        try:
            self._router  = ProviderRouter(config)
            self._handler = RequestHandler(
                vault_path    = self._vault_path,
                router        = self._router,
                registry      = registry,       # ← NEW
                system_prompt = system_prompt,
            )
        except Exception as exc:
            logger.error(f"[VaultWatcher] Failed to initialise: {exc}")
            raise

        logger.info(f"[VaultWatcher] Initialised — vault: {self._vault_path}")
        logger.info(f"[VaultWatcher] Poll interval: {self._poll_interval}s")
        if registry:
            logger.info(f"[VaultWatcher] Registry loaded — {len(registry.tool_names)} tools")
        else:
            logger.warning("[VaultWatcher] No registry — agent tools disabled in watcher")
        if system_prompt:
            logger.info("[VaultWatcher] Full system prompt loaded")
        else:
            logger.warning("[VaultWatcher] No system prompt — using default stub")

    def run(self) -> None:
        self._running = True
        logger.info("[VaultWatcher] Starting watcher loop...")

        try:
            while self._running:
                try:
                    self._check_vault()
                    time.sleep(self._poll_interval)
                except KeyboardInterrupt:
                    break
                except Exception as exc:
                    logger.error(f"[VaultWatcher] Error in check loop: {exc}")
                    time.sleep(self._poll_interval)
        finally:
            self._running = False
            logger.info("[VaultWatcher] Watcher stopped")

    def _check_vault(self) -> None:
        # Re-indexing is capped per pass and the store is saved ONCE at the end (not per note), so a
        # mass change (e.g. a migration touching thousands of notes) is spread over several passes and
        # never holds the GIL long enough to starve the HTTP event loop. The rest carry over next pass.
        self._reindexed_this_pass = 0
        for md_file in self._vault.rglob("*.md"):
            self._check_file(md_file)
            if self._reindexed_this_pass >= self._reindex_cap:
                break   # leave the rest for the next poll — keeps each pass short
        if self._reindexed_this_pass and self._rag:
            try:
                self._rag.save_index()
            except Exception as exc:
                logger.debug(f"[VaultWatcher] index save failed: {exc}")

    def _check_file(self, filepath: Path) -> None:
        """Single read passed to process() — eliminates TOCTOU race."""
        try:
            mtime    = filepath.stat().st_mtime
            file_key = str(filepath)
            last     = self._last_check.get(file_key, 0)

            if mtime <= last:
                return

            self._last_check[file_key] = mtime

            try:
                content = filepath.read_text(encoding="utf-8")
            except Exception as exc:
                logger.debug(f"[VaultWatcher] Could not read {filepath.name}: {exc}")
                return

            fm_dict, body = FrontmatterParser.extract(content)
            status        = fm_dict.get("assistant-status", "").lower().strip('"')
            rel_path      = str(filepath.relative_to(self._vault))

            # M11 — keep the Vault QA index fresh: re-embed a note only when it
            # actually changed (hash-checked). Only the indexing machine does this.
            if self._rag and self._rag.enabled:
                try:
                    # save=False: the whole-store write is batched to once per pass (see _check_vault).
                    if self._rag.maybe_index_note(rel_path, content, save=False):
                        self._reindexed_this_pass += 1
                        time.sleep(self._reindex_throttle)   # yield so the event loop stays responsive
                except Exception as exc:
                    logger.debug(f"[VaultWatcher] RAG index of {rel_path} failed: {exc}")

            if status == "pending":
                request = fm_dict.get("assistant-request", "").strip().strip('"')
                if not request:
                    return

                logger.info(f"[VaultWatcher] Found pending: {rel_path}")
                success = self._handler.process(rel_path, request, content=content)

                ts = datetime.now().strftime("%H:%M:%S")
                if success:
                    print(f"✓ [{ts}] {rel_path} — Done")
                else:
                    try:
                        updated       = filepath.read_text(encoding="utf-8")
                        updated_fm, _ = FrontmatterParser.extract(updated)
                        new_status    = updated_fm.get("assistant-status", "").strip('"')
                        if new_status == "handoff-pending":
                            print(f"🌐 [{ts}] {rel_path} — Handoff pending")
                        elif new_status == "proposal-pending":
                            print(f"📝 [{ts}] {rel_path} — Edit proposal staged (review in plugin)")
                        elif new_status == "error":
                            print(f"⚠ [{ts}] {rel_path} — Error (see note)")
                        else:
                            print(f"✗ [{ts}] {rel_path} — Failed")
                    except Exception:
                        print(f"✗ [{ts}] {rel_path} — Failed")

            elif status == "handoff-pending":
                if "## User Web Handoff Return" not in body:
                    return
                after       = body.split("## User Web Handoff Return", 1)[1].strip()
                placeholder = "*(Paste the web AI response here"
                if not after or after.startswith(placeholder):
                    return

                logger.info(f"[VaultWatcher] Found handoff return: {rel_path}")
                success = self._handler.inject_handoff_return(rel_path)
                ts      = datetime.now().strftime("%H:%M:%S")
                print(
                    f"{'✓' if success else '✗'} [{ts}] {rel_path} — "
                    f"Handoff return {'injected' if success else 'failed'}"
                )

        except Exception as exc:
            logger.error(f"[VaultWatcher] Error checking {filepath}: {exc}")

    def stop(self) -> None:
        self._running = False


def main() -> None:
    config     = ConfigManager()
    logger_obj = setup_logger(config.get("log_level", "INFO"), verbose=False)
    logger_obj.info("Vault Watcher starting")

    try:
        watcher = VaultWatcher(
            config.all(),
            poll_interval = config.get("watcher_poll_interval", 5),
        )
        watcher.run()
    except KeyboardInterrupt:
        logger_obj.info("Watcher interrupted")
    except Exception as exc:
        logger_obj.error(f"Watcher failed: {exc}")
        raise


if __name__ == "__main__":
    main()

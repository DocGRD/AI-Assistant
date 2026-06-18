"""
Vault Watcher — headless fixes

T7.5.10 fix (TOCTOU race condition):
  _check_file() now passes the already-read file content into process().
  Previously vault_watcher read the file, confirmed status=pending, then
  called process() which read the file AGAIN. If Obsidian autosaved between
  those two reads (very common), the second read could see different content
  causing process() to return False with "status != pending".
  Now: one read, one process() call, no race.

T7.5.11 fix (headless shutdown on Windows):
  run_headless() now uses a polling loop with a short sleep instead of
  threading.Event().wait(). This is reliably interrupted by KeyboardInterrupt
  (Ctrl+C) on both Windows and Linux. The signal handler approach using
  threading.Event().wait() was not reliably woken by SIGINT on Windows.

Additional: /shutdown HTTP endpoint added so the plugin's "exit"/"quit"
  messages can trigger a clean shutdown. POST /chat also intercepts
  "exit" and "quit" as special messages and calls /shutdown internally.
"""

import logging
import time
import threading
from pathlib import Path
from datetime import datetime

from config.config_manager import ConfigManager
from config.logger import setup_logger
from providers.provider_router import ProviderRouter
from watcher.frontmatter_parser import FrontmatterParser
from watcher.request_handler import RequestHandler

logger = logging.getLogger("watcher")


class VaultWatcher:

    def __init__(self, config: dict, poll_interval: int = 5, system_prompt: str = ""):
        self._vault_path    = config.get("vault_path", "")
        self._vault         = Path(self._vault_path)
        self._poll_interval = poll_interval
        self._last_check:   dict[str, float] = {}
        self._running       = False

        if not self._vault.exists():
            raise ValueError(f"Vault path does not exist: {self._vault_path}")

        try:
            self._router  = ProviderRouter(config)
            self._handler = RequestHandler(
                vault_path    = self._vault_path,
                router        = self._router,
                system_prompt = system_prompt,
            )
        except Exception as exc:
            logger.error(f"[VaultWatcher] Failed to initialise: {exc}")
            raise

        logger.info(f"[VaultWatcher] Initialised — vault: {self._vault_path}")
        logger.info(f"[VaultWatcher] Poll interval: {self._poll_interval}s")
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
        for md_file in self._vault.rglob("*.md"):
            self._check_file(md_file)

    def _check_file(self, filepath: Path) -> None:
        """
        Check one file for pending requests.
        T7.5.10 fix: read the file ONCE here and pass the content
        directly into process() — eliminates the TOCTOU race where
        Obsidian autosave could change the file between the watcher's
        status check and process()'s own re-read.
        """
        try:
            mtime    = filepath.stat().st_mtime
            file_key = str(filepath)
            last     = self._last_check.get(file_key, 0)

            if mtime <= last:
                return

            self._last_check[file_key] = mtime

            # T7.5.10: single read, passed to both status-check and process()
            try:
                content = filepath.read_text(encoding="utf-8")
            except Exception as exc:
                logger.debug(f"[VaultWatcher] Could not read {filepath.name}: {exc}")
                return

            fm_dict, body = FrontmatterParser.extract(content)
            status   = fm_dict.get("assistant-status", "").lower().strip('"')
            rel_path = str(filepath.relative_to(self._vault))

            if status == "pending":
                request = fm_dict.get("assistant-request", "").strip().strip('"')
                if not request:
                    logger.debug(f"[VaultWatcher] pending but no request: {rel_path}")
                    return

                logger.info(f"[VaultWatcher] Found pending: {rel_path}")

                # T7.5.10: pass content so process() doesn't re-read
                success = self._handler.process(rel_path, request, content=content)

                ts = datetime.now().strftime("%H:%M:%S")
                if success:
                    print(f"✓ [{ts}] {rel_path} — Done")
                else:
                    # Re-read to show updated status
                    try:
                        updated       = filepath.read_text(encoding="utf-8")
                        updated_fm, _ = FrontmatterParser.extract(updated)
                        new_status    = updated_fm.get("assistant-status", "").strip('"')
                        if new_status == "handoff-pending":
                            print(f"🌐 [{ts}] {rel_path} — Handoff pending (paste response in note)")
                        elif new_status == "error":
                            print(f"⚠ [{ts}] {rel_path} — Error (see note for details)")
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

                ts = datetime.now().strftime("%H:%M:%S")
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

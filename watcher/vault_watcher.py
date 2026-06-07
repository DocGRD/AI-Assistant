"""
Vault Watcher — Monitor vault for assistant requests via YAML frontmatter.

Watches for file changes in the vault. When a .md file is modified,
checks if it has assistant-status: pending. If yes, processes the request.

Runs as a background daemon, checking changes every N seconds.
"""

import logging
import time
from pathlib import Path
from datetime import datetime

from config.config_manager import ConfigManager
from config.logger import setup_logger
from providers.provider_router import ProviderRouter
from providers.base_provider import ProviderError
from watcher.frontmatter_parser import FrontmatterParser
from watcher.request_handler import RequestHandler

logger = logging.getLogger("watcher")


class VaultWatcher:
    """Monitors vault for assistant requests."""

    def __init__(self, config: dict, poll_interval: int = 5):
        """
        Initialize the vault watcher.

        Args:
            config: Settings dictionary (from ConfigManager)
            poll_interval: How often to check for changes (seconds)
        """
        self._vault_path = config.get("vault_path", "")
        self._vault = Path(self._vault_path)
        self._poll_interval = poll_interval
        self._last_check = {}  # Track file modification times
        self._running = False

        if not self._vault.exists():
            raise ValueError(f"Vault path does not exist: {self._vault_path}")

        # Initialize router and handler
        try:
            self._router = ProviderRouter(config)
            self._handler = RequestHandler(self._vault_path, self._router)
        except Exception as exc:
            logger.error(f"[VaultWatcher] Failed to initialize router: {exc}")
            raise

        logger.info(f"[VaultWatcher] Initialized for vault: {self._vault_path}")
        logger.info(f"[VaultWatcher] Poll interval: {self._poll_interval}s")

    def run(self) -> None:
        """
        Start the watcher loop. Runs indefinitely until stopped.
        Press Ctrl+C to stop.
        """
        self._running = True
        logger.info("[VaultWatcher] Starting watcher loop...")
        print(f"\n{'='*60}")
        print("  VAULT WATCHER — Active")
        print(f"  Vault: {self._vault_path}")
        print(f"  Poll interval: {self._poll_interval}s")
        print("  Watching for assistant-status: pending")
        print("  Press Ctrl+C to stop")
        print(f"{'='*60}\n")

        try:
            while self._running:
                try:
                    self._check_vault()
                    time.sleep(self._poll_interval)
                except KeyboardInterrupt:
                    logger.info("[VaultWatcher] Interrupted by user")
                    break
                except Exception as exc:
                    logger.error(f"[VaultWatcher] Error in check loop: {exc}")
                    time.sleep(self._poll_interval)
        finally:
            self._running = False
            logger.info("[VaultWatcher] Watcher stopped")
            print("\n[Watcher stopped]\n")

    def _check_vault(self) -> None:
        """Check all .md files for pending requests."""
        for md_file in self._vault.rglob("*.md"):
            self._check_file(md_file)

    def _check_file(self, filepath: Path) -> None:
        """
        Check a single .md file for pending requests.
        If modified since last check, parse and process if needed.
        """
        try:
            stat = filepath.stat()
            mtime = stat.st_mtime

            # Track modification times to avoid re-processing
            file_key = str(filepath)
            last_mtime = self._last_check.get(file_key, 0)

            if mtime <= last_mtime:
                return  # No change since last check

            self._last_check[file_key] = mtime

            # Read and parse the file
            try:
                content = filepath.read_text(encoding="utf-8")
            except Exception as exc:
                logger.debug(f"[VaultWatcher] Could not read {filepath.name}: {exc}")
                return

            # Extract frontmatter
            fm_dict, body = FrontmatterParser.extract(content)

            # Check for pending request
            status = fm_dict.get("assistant-status", "").lower()
            if status != "pending":
                return

            request = fm_dict.get("assistant-request", "").strip()
            if not request:
                logger.debug(f"[VaultWatcher] Pending status but no request in {filepath.name}")
                return

            # Found a pending request!
            rel_path = filepath.relative_to(self._vault)
            logger.info(f"[VaultWatcher] Found pending request: {rel_path}")
            logger.info(f"[VaultWatcher] Request: {request[:80]}")

            # Process it
            success = self._handler.process(str(rel_path), request)

            if success:
                logger.info(f"[VaultWatcher] ✓ Processed: {rel_path}")
                print(f"✓ [{datetime.now().strftime('%H:%M:%S')}] {rel_path} — Done")
            else:
                logger.warning(f"[VaultWatcher] ✗ Failed to process: {rel_path}")
                # Get the updated frontmatter to show the reason
                try:
                    updated_content = filepath.read_text(encoding="utf-8")
                    updated_fm, _ = FrontmatterParser.extract(updated_content)
                    status = updated_fm.get("assistant-status", "unknown")
                    if status == "error":
                        print(f"⚠ [{datetime.now().strftime('%H:%M:%S')}] {rel_path} — Error (see note for details)")
                    else:
                        print(f"✗ [{datetime.now().strftime('%H:%M:%S')}] {rel_path} — Failed")
                except:
                    print(f"✗ [{datetime.now().strftime('%H:%M:%S')}] {rel_path} — Failed")

        except Exception as exc:
            logger.error(f"[VaultWatcher] Error checking {filepath}: {exc}")

    def stop(self) -> None:
        """Stop the watcher loop."""
        self._running = False


def main() -> None:
    """Entry point for standalone watcher process."""
    config = ConfigManager()
    logger_obj = setup_logger(config.get("log_level", "INFO"), verbose=False)
    logger_obj.info("Vault Watcher starting — Milestone 5.5")

    try:
        watcher = VaultWatcher(
            config.all(),
            poll_interval=config.get("watcher_poll_interval", 5),
        )
        watcher.run()
    except KeyboardInterrupt:
        logger_obj.info("Watcher interrupted")
    except Exception as exc:
        logger_obj.error(f"Watcher failed: {exc}")
        print(f"\nError: {exc}\n")
        raise


if __name__ == "__main__":
    main()

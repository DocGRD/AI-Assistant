"""
Logger Setup
Configures logging with two independent handlers:
    - File handler   : always on, writes everything to logs/assistant.log
    - Console handler: off by default, toggled at runtime via set_verbose()

This keeps the chat UI clean while preserving full diagnostic logs on disk.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Module-level reference so set_verbose() can reach the console handler
# from anywhere in the codebase without passing the logger around.
_console_handler: logging.StreamHandler | None = None


def setup_logger(level: str = "INFO", verbose: bool = False) -> logging.Logger:
    """
    Return a configured logger.

    Args:
        level:   Log level string for the FILE handler ("DEBUG", "INFO", etc.)
        verbose: If True, also print logs to the console on startup.
                 Can be toggled later with set_verbose().
    """
    global _console_handler

    log_level = getattr(logging, level.upper(), logging.INFO)

    logs_dir = Path(__file__).parent.parent / "logs"
    logs_dir.mkdir(exist_ok=True)
    log_file = logs_dir / "assistant.log"

    logger = logging.getLogger("assistant")
    logger.setLevel(log_level)

    if logger.handlers:
        # Already configured — just honour the verbose flag and return.
        set_verbose(verbose)
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # ── File handler (always on, rotates at 1 MB, keeps 3 backups) ──────
    fh = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # ── Console handler (off by default) ────────────────────────────────
    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(formatter)
    _console_handler.setLevel(logging.CRITICAL + 1)  # effectively disabled
    logger.addHandler(_console_handler)

    if verbose:
        set_verbose(True)

    return logger


def set_verbose(enabled: bool) -> None:
    """
    Turn console log output on or off at runtime.
    File logging is unaffected.

    Called by:
        assistant.py when the user types 'verbose on' or 'verbose off'
    """
    global _console_handler
    if _console_handler is None:
        return
    if enabled:
        _console_handler.setLevel(logging.DEBUG)
    else:
        _console_handler.setLevel(logging.CRITICAL + 1)  # silent


def is_verbose() -> bool:
    """Return True if console logging is currently enabled."""
    if _console_handler is None:
        return False
    return _console_handler.level <= logging.DEBUG

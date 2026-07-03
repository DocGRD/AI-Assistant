"""
Logger Setup — Milestone 7.5 (BUG-007: daily log rotation)

Changes from M7:
  - Replaced RotatingFileHandler (size-based) with TimedRotatingFileHandler
    (rotates at midnight, keeps 7 daily backups).
  - Log files are now named assistant.log.YYYY-MM-DD, one per day.
  - The active file is always assistant.log; yesterday's becomes assistant.log.2026-06-09 etc.
"""

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_console_handler: logging.StreamHandler | None = None


def setup_logger(level: str = "INFO", verbose: bool = False) -> logging.Logger:
    global _console_handler

    log_level = getattr(logging, level.upper(), logging.INFO)

    from assistant_core.paths import LOGS_DIR
    LOGS_DIR.mkdir(exist_ok=True)
    log_file = LOGS_DIR / "assistant.log"

    logger = logging.getLogger("assistant")
    logger.setLevel(log_level)

    if logger.handlers:
        set_verbose(verbose)
        return logger

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # BUG-007: rotate at midnight, keep 7 days of logs
    fh = TimedRotatingFileHandler(
        log_file,
        when        = "midnight",
        backupCount = 7,
        encoding    = "utf-8",
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    _console_handler = logging.StreamHandler()
    _console_handler.setFormatter(formatter)
    _console_handler.setLevel(logging.CRITICAL + 1)
    logger.addHandler(_console_handler)

    if verbose:
        set_verbose(True)

    return logger


def set_verbose(enabled: bool) -> None:
    global _console_handler
    if _console_handler is None:
        return
    if enabled:
        _console_handler.setLevel(logging.DEBUG)
    else:
        _console_handler.setLevel(logging.CRITICAL + 1)


def is_verbose() -> bool:
    if _console_handler is None:
        return False
    return _console_handler.level <= logging.DEBUG

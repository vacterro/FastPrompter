"""Simple logging utility for FastPrompter.

Replaces scattered ``print()`` and ``traceback.print_exc()`` calls
with a consistent ``logger`` instance that writes to both stderr
and a rotating log file (``crash.log``).

Usage::

    from fastprompter.core.logging import logger

    logger.debug("Entering method foo")
    logger.info("Window shown")
    logger.error("Failed to save: %s", exc_info=e)
"""

import logging
import os
import sys
import tempfile
import traceback
from logging.handlers import RotatingFileHandler

_LOG_FILE: str = os.path.join(tempfile.gettempdir(), "fastprompter.log")


def _setup_logger() -> logging.Logger:
    """Create and configure the application-level logger instance."""
    log = logging.getLogger("fastprompter")
    log.setLevel(logging.DEBUG)

    # Prevent duplicate handlers when the module is reloaded
    if log.handlers:
        return log

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # File handler with rotation (max 1 MB, keep 2 backups)
    try:
        fh: RotatingFileHandler = RotatingFileHandler(
            _LOG_FILE, maxBytes=1_048_576, backupCount=2, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception:
        log.debug("Failed to set up file logger, continuing without it")

    # Stderr handler (always visible in terminal)
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(fmt)
    log.addHandler(sh)

    return log


# Singleton logger instance
logger: logging.Logger = _setup_logger()


def exception_hook(exctype: type, value: BaseException, tb: object | None) -> None:
    """Unhandled exception hook that logs the full traceback and shows a crash dialog.

    Designed to be used with ``sys.excepthook``.
    """
    error_msg: str = "".join(traceback.format_exception(exctype, value, tb))
    logger.critical("Unhandled exception:\n%s", error_msg)

    # Also write to a crash-specific log file
    crash_path: str = os.path.join(tempfile.gettempdir(), "fastprompter_crash.log")
    try:
        with open(crash_path, "a", encoding="utf-8") as f:
            f.write(f"\n--- {__import__('datetime').datetime.now()} ---\n")
            f.write(error_msg)
    except Exception:
        logger.debug("Failed to write to crash log file")

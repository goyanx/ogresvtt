"""
Centralized logging setup for the AI DM sidecar.

Writes logs to logs/ai_dm.log (configurable via env vars):
  AI_DM_LOG_DIR
  AI_DM_LOG_FILE
  AI_DM_LOG_LEVEL
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_logging() -> Path:
    """
    Configure process-wide logging once and return the log file path.
    """
    log_dir = Path(os.getenv("AI_DM_LOG_DIR", "logs"))
    log_file_name = os.getenv("AI_DM_LOG_FILE", "ai_dm.log")
    log_level = os.getenv("AI_DM_LOG_LEVEL", "INFO").upper()
    log_path = log_dir / log_file_name
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    if getattr(root, "_ai_dm_configured", False):
        return log_path

    root.setLevel(getattr(logging, log_level, logging.INFO))
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    # Keep noisy libraries at warning-level by default.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    root._ai_dm_configured = True  # type: ignore[attr-defined]
    logging.getLogger(__name__).info("AI DM logging configured: %s", log_path)
    return log_path


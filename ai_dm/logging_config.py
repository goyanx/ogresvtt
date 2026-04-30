"""
Centralized logging config for AI DM sidecar.
"""
import logging
import os
from pathlib import Path


def configure_logging() -> Path:
    log_dir = Path(os.getenv("AI_DM_LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / os.getenv("AI_DM_LOG_FILE", "ai_dm.log")
    level_name = os.getenv("AI_DM_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    # Clear existing handlers to avoid duplicates on reload.
    for h in list(root.handlers):
        root.removeHandler(h)

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(fmt)
    root.addHandler(stream_handler)

    logging.getLogger("uvicorn").setLevel(level)
    logging.getLogger("uvicorn.error").setLevel(level)
    logging.getLogger("uvicorn.access").setLevel(level)

    logging.getLogger(__name__).info("AI DM logging configured: %s", log_file)
    return log_file

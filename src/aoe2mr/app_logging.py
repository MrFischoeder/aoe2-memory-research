"""Application logging setup (named ``app_logging`` to avoid shadowing stdlib ``logging``)."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aoe2mr.config import LoggingConfig

LOGGER_NAME = "aoe2mr"
_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def configure_logging(cfg: LoggingConfig, log_dir: Path | None = None) -> logging.Logger:
    """Configure the ``aoe2mr`` logger. Safe to call more than once."""
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(cfg.level)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(_FORMAT))
    logger.addHandler(console)

    if log_dir is not None:
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / cfg.file_name,
            maxBytes=cfg.max_bytes,
            backupCount=cfg.backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(file_handler)

    logger.propagate = False
    return logger


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{name}")

"""Logging configuration for omniModel."""

from __future__ import annotations

import logging
import sys

from .config import config


def setup_logging() -> logging.Logger:
    """Configure root logging and return the omniModel logger."""
    root = logging.getLogger()
    # Avoid duplicate handlers if called twice.
    for handler in list(root.handlers):
        root.removeHandler(handler)

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(config.log_format))
    root.addHandler(handler)
    root.setLevel(config.log_level)

    logger = logging.getLogger("omnimodel")
    logger.setLevel(config.log_level)
    return logger


# Eagerly configure on import so library code can just call
# ``logging.getLogger("omnimodel")``.
logger = setup_logging()
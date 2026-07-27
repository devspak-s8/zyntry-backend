from __future__ import annotations

import logging
import sys
from logging.config import dictConfig

from app.core.config import settings


def configure_logging() -> None:
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "[%(asctime)s] %(levelname)s in %(name)s: %(message)s",
                },
                "json": {
                    "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "stream": sys.stdout,
                    "formatter": "default",
                },
            },
            "root": {
                "level": settings.LOG_LEVEL.upper(),
                "handlers": ["console"],
            },
            "loggers": {
                "uvicorn": {"level": settings.LOG_LEVEL.upper()},
                "app": {"level": settings.LOG_LEVEL.upper()},
            },
        }
    )


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

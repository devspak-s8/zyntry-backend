#!/usr/bin/env python3
"""Standalone Runtime Assistant Service.

Runs independently from the FastAPI process and exposes an internal HTTP API
for runtime chat, recommendations, optimization, diagnostics, planning,
execution, and memory management.
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_models
from app.core.logging import configure_logging

configure_logging()
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Zyntra Runtime Assistant",
    version="1.0.0",
    description="Standalone Runtime Assistant Service",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "runtime-assistant"}


@app.get("/ready")
async def ready() -> dict[str, str]:
    return {"status": "ready", "service": "runtime-assistant"}


@app.on_event("startup")
async def startup() -> None:
    await init_models()
    logger.info("Runtime Assistant Service started successfully")


def main() -> None:
    uvicorn.run(
        "scripts.runtime_assistant:app",
        host="0.0.0.0",
        port=8001,
        log_level=settings.LOG_LEVEL.lower(),
        reload=settings.APP_DEBUG,
    )


if __name__ == "__main__":
    main()

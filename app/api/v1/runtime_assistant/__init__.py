from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.runtime_assistant.router import router as runtime_assistant_router

router = APIRouter()
router.include_router(runtime_assistant_router)

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1 import api_router as v1_router

router = APIRouter()
router.include_router(v1_router)

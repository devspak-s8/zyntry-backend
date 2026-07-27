from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.services.model_discovery import get_model_discovery


class ModelInfo(BaseModel):
    id: str
    name: str
    provider: str
    max_context: int
    supports_vision: bool
    supports_tools: bool
    supports_streaming: bool
    input_price_per_1k: float | None = None
    output_price_per_1k: float | None = None
    latency_tier: str = "medium"
    quality_tier: str = "standard"
    config: dict = {}


class ModelProvider(BaseModel):
    name: str
    display_name: str
    connected: bool
    models: list[ModelInfo]
    model_count: int


class ModelTestRequest(BaseModel):
    provider: str
    model: str
    api_key: str | None = None


class ModelTestResult(BaseModel):
    success: bool
    latency_ms: int
    model: str
    provider: str
    error: str | None = None


class ModelRefreshResponse(BaseModel):
    refreshed_at: str
    providers: list[ModelProvider]
    total_models: int


router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelInfo])
async def list_models(
    provider: str | None = Query(None),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> list[ModelInfo]:
    discovery = get_model_discovery()
    all_providers = await discovery.discover_all_models()
    all_models: list[ModelInfo] = []
    for p in all_providers:
        if provider and p["name"].lower() != provider.lower() and p["display_name"].lower() != provider.lower():
            continue
        for m in p.get("models", []):
            all_models.append(ModelInfo(**m))
    return all_models


@router.get("/providers", response_model=list[ModelProvider])
async def list_model_providers(
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> list[ModelProvider]:
    discovery = get_model_discovery()
    all_providers = await discovery.discover_all_models()
    result: list[ModelProvider] = []
    for p in all_providers:
        models = [ModelInfo(**m) for m in p.get("models", [])]
        result.append(ModelProvider(
            name=p["name"],
            display_name=p["display_name"],
            connected=p["connected"],
            models=models,
            model_count=p["model_count"],
        ))
    return result


@router.get("/{model_id}", response_model=ModelInfo)
async def get_model(
    model_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> ModelInfo:
    discovery = get_model_discovery()
    all_providers = await discovery.discover_all_models()
    for p in all_providers:
        for m in p.get("models", []):
            if m["id"] == model_id or m["name"] == model_id:
                return ModelInfo(**m)
    raise HTTPException(status_code=404, detail="Model not found")


@router.post("/test", response_model=ModelTestResult)
async def test_model(
    body: ModelTestRequest,
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> ModelTestResult:
    import time
    start = time.time()
    discovery = get_model_discovery()
    all_providers = await discovery.discover_all_models()
    for p in all_providers:
        for m in p.get("models", []):
            if m["provider"].lower() == body.provider.lower() and m["name"].lower() == body.model.lower():
                latency = int((time.time() - start) * 1000)
                return ModelTestResult(
                    success=True,
                    latency_ms=latency,
                    model=m["name"],
                    provider=p["name"],
                    error=None,
                )
    raise HTTPException(status_code=404, detail="Model not found")


@router.post("/refresh", response_model=ModelRefreshResponse)
async def refresh_models(
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> ModelRefreshResponse:
    discovery = get_model_discovery()
    providers = await discovery.refresh_models()
    total = sum(p["model_count"] for p in providers)
    return ModelRefreshResponse(
        refreshed_at=datetime.utcnow().isoformat(),
        providers=[ModelProvider(
            name=p["name"],
            display_name=p["display_name"],
            connected=p["connected"],
            models=[ModelInfo(**m) for m in p.get("models", [])],
            model_count=p["model_count"],
        ) for p in providers],
        total_models=total,
    )
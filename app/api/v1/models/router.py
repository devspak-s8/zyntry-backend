from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_project_membership
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.services.model_discovery import get_model_discovery
from app.services.model_registry import list_registered_models
from app.services.provider_health import provider_health
from app.services.providers import ProviderService


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
    max_output_tokens: int = 8192
    supports_reasoning: bool = False
    supports_structured_output: bool = False
    supports_embeddings: bool = False
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


class ProviderHealthInfo(BaseModel):
    provider: str
    available: bool
    consecutive_failures: int = 0
    total_failures: int = 0
    total_successes: int = 0
    last_latency_ms: float | None = None
    last_error: str | None = None
    last_checked_at: str | None = None
    unhealthy_until: float | None = None


router = APIRouter(prefix="/models", tags=["models"])


@router.get("", response_model=list[ModelInfo])
async def list_models(
    provider: str | None = Query(None),
    project_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[ModelInfo]:
    if project_id:
        await require_project_membership(project_id, current_user, db)
    discovery = get_model_discovery()
    uow = UnitOfWork(db)
    service = ProviderService(uow)
    connections = await service.list_providers(
        project_id,
        organization_id=str(current_user.organization_id) if not project_id else None,
    )
    connected_names = {c["provider_name"] for c in connections if c.get("status") == "active"}

    all_models: list[ModelInfo] = []
    if provider:
        provider_name = provider.lower()
        for p_name in connected_names:
            if p_name.lower() == provider_name:
                try:
                    models_raw = await asyncio.wait_for(
                        discovery.get_models_by_provider(p_name),
                        timeout=10.0,
                    )
                    for m in models_raw:
                        all_models.append(ModelInfo(**discovery._model_to_dict(m)))
                except Exception:
                    pass
                break
    else:
        async def _fetch_models(name: str) -> list[ModelInfo]:
            try:
                models_raw = await asyncio.wait_for(
                    discovery.get_models_by_provider(name),
                    timeout=10.0,
                )
                return [ModelInfo(**discovery._model_to_dict(m)) for m in models_raw]
            except Exception:
                return []

        results = await asyncio.gather(
            *[_fetch_models(name) for name in connected_names],
            return_exceptions=True,
        )
        for models in results:
            if isinstance(models, BaseException):
                continue
            all_models.extend(models)
    return all_models


@router.get("/providers", response_model=list[ModelProvider])
async def list_model_providers(
    project_id: str | None = Query(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> list[ModelProvider]:
    if project_id:
        await require_project_membership(project_id, current_user, db)
    discovery = get_model_discovery()
    all_providers = await discovery.discover_all_models()
    uow = UnitOfWork(db)
    service = ProviderService(uow)
    connections = await service.list_providers(
        project_id,
        organization_id=str(current_user.organization_id) if not project_id else None,
    )
    connected_names = {c["provider_name"] for c in connections if c.get("status") == "active"}

    async def _fetch_provider_models(name: str):
        try:
            models_raw = await asyncio.wait_for(
                discovery.get_models_by_provider(name),
                timeout=10.0,
            )
            return name, [discovery._model_to_dict(m) for m in models_raw], len(models_raw)
        except Exception:
            return name, [], 0

    connected_providers = [p for p in all_providers if p["name"] in connected_names]
    results = await asyncio.gather(
        *[_fetch_provider_models(p["name"]) for p in connected_providers],
        return_exceptions=True,
    )
    model_map: dict[str, tuple[list[dict], int]] = {}
    for r in results:
        if isinstance(r, BaseException):
            continue
        name, models, count = r
        model_map[name] = (models, count)

    for p in all_providers:
        if p["name"] in connected_names:
            p["connected"] = True
            p["models"], p["model_count"] = model_map.get(p["name"], ([], 0))
        else:
            p["connected"] = False
            p["models"] = []
            p["model_count"] = 0
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


@router.get("/registry", response_model=list[ModelInfo])
async def list_model_registry(
    provider: str | None = Query(None),
    current_user: User = Depends(get_current_user),
) -> list[ModelInfo]:
    """Return Zyntry's provider-neutral model capability registry.

    Unlike ``GET /models``, this endpoint does not call provider APIs and does
    not require provider credentials.  It is suitable for routing preflight,
    context budgeting, and displaying model capabilities in the console.
    """

    return [ModelInfo(**item.as_dict()) for item in list_registered_models(provider)]


@router.get("/health", response_model=list[ProviderHealthInfo])
async def list_provider_health(
    current_user: User = Depends(get_current_user),
) -> list[ProviderHealthInfo]:
    """Return best-effort provider availability observed by this API worker."""

    return [ProviderHealthInfo(**item) for item in provider_health.snapshot()]


@router.get("/{model_id}", response_model=ModelInfo)
async def get_model(
    model_id: str,
    current_user: User = Depends(get_current_user),
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ModelTestResult:
    import time
    start = time.time()
    discovery = get_model_discovery()
    uow = UnitOfWork(db)
    service = ProviderService(uow)
    connections = await service.list_providers(
        organization_id=str(current_user.organization_id) if current_user.organization_id else None
    )
    connected_names = {c["provider_name"] for c in connections if c.get("status") == "active"}
    for provider_name in connected_names:
        if provider_name.lower() != body.provider.lower():
            continue
        try:
            models_raw = await discovery.get_models_by_provider(provider_name)
            for m in models_raw:
                if m.name.lower() == body.model.lower():
                    latency = int((time.time() - start) * 1000)
                    return ModelTestResult(
                        success=True,
                        latency_ms=latency,
                        provider=provider_name,
                        model=m.name,
                    )
        except Exception:
            pass
        break
    raise HTTPException(status_code=404, detail="Model not found or provider not connected")


@router.post("/refresh", response_model=ModelRefreshResponse)
async def refresh_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_session),
) -> ModelRefreshResponse:
    discovery = get_model_discovery()
    uow = UnitOfWork(db)
    service = ProviderService(uow)
    connections = await service.list_providers()
    connected_names = {c["provider_name"] for c in connections if c.get("status") == "active"}

    all_providers = await discovery.discover_all_models()
    refreshed: list[ModelProvider] = []
    total_models = 0

    async def _fetch_provider_models(name: str):
        try:
            models_raw = await asyncio.wait_for(
                discovery.get_models_by_provider(name),
                timeout=10.0,
            )
            return name, [ModelInfo(**discovery._model_to_dict(m)) for m in models_raw], len(models_raw)
        except Exception:
            return name, [], 0

    connected_providers = [p for p in all_providers if p["name"] in connected_names]
    results = await asyncio.gather(
        *[_fetch_provider_models(p["name"]) for p in connected_providers],
        return_exceptions=True,
    )
    model_map: dict[str, tuple[list[ModelInfo], int]] = {}
    for r in results:
        if isinstance(r, BaseException):
            continue
        name, models, count = r
        model_map[name] = (models, count)

    for p in all_providers:
        if p["name"] in connected_names:
            models, count = model_map.get(p["name"], ([], 0))
            refreshed.append(ModelProvider(
                name=p["name"],
                display_name=p["display_name"],
                connected=True,
                models=models,
                model_count=count,
            ))
            total_models += count
        else:
            refreshed.append(ModelProvider(
                name=p["name"],
                display_name=p["display_name"],
                connected=False,
                models=[],
                model_count=0,
            ))
    return ModelRefreshResponse(
        refreshed_at=datetime.now(UTC).isoformat(),
        providers=refreshed,
        total_models=total_models,
    )

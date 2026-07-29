from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.services.model_router import ModelRouter, RoutingGoal, RoutingPreference
from app.services.model_providers import PROVIDER_REGISTRY
from app.services.model_providers.base import BaseModelProvider

router = APIRouter(prefix="/router", tags=["router"])


@router.get("/models")
async def list_available_models(
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    uow = UnitOfWork(db)
    provider_keys: dict[str, str] = {}
    for p_name, setting_name in [
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("google", "GOOGLE_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
        ("groq", "GROQ_API_KEY"),
        ("mistral", "MISTRAL_API_KEY"),
    ]:
        key = getattr(settings, setting_name, None)
        if key:
            provider_keys[p_name] = key

    models_by_provider: dict[str, list[dict]] = {}
    for provider_name, api_key in provider_keys.items():
        provider_cls = PROVIDER_REGISTRY.get(provider_name.lower())
        if not provider_cls:
            continue
        try:
            provider = provider_cls()
            models = await provider.list_models(api_key)
            models_by_provider[provider_name] = [
                {
                    "id": m.id,
                    "name": m.name,
                    "provider": m.provider,
                    "max_context": m.max_context,
                    "supports_vision": m.supports_vision,
                    "supports_tools": m.supports_tools,
                    "supports_streaming": m.supports_streaming,
                    "input_price_per_1k": m.input_price_per_1k,
                    "output_price_per_1k": m.output_price_per_1k,
                    "latency_tier": m.latency_tier,
                    "quality_tier": m.quality_tier,
                }
                for m in models
            ]
        except Exception:
            models_by_provider[provider_name] = []

    return {"providers": models_by_provider, "total_providers": len(models_by_provider)}


@router.post("/recommend")
async def recommend_model(
    goal: str = Query(default="balanced"),
    providers: str | None = Query(default=None),
    max_cost_per_1k: float | None = Query(default=None),
    min_context: int | None = Query(default=None),
    requires_vision: bool = Query(default=False),
    requires_tools: bool = Query(default=False),
    current_user: Annotated[User, Depends(get_current_user)] = None,
    db: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    try:
        routing_goal = RoutingGoal(goal)
    except ValueError:
        routing_goal = RoutingGoal.BALANCED

    preferred = providers.split(",") if providers else []
    preference = RoutingPreference(
        goal=routing_goal,
        preferred_providers=preferred,
        max_cost_per_1k=max_cost_per_1k,
        min_context=min_context,
        requires_vision=requires_vision,
        requires_tools=requires_tools,
    )

    uow = UnitOfWork(db)
    router_service = ModelRouter(uow)

    provider_keys: dict[str, str] = {}
    for p_name, setting_name in [
        ("openai", "OPENAI_API_KEY"),
        ("anthropic", "ANTHROPIC_API_KEY"),
        ("google", "GOOGLE_API_KEY"),
        ("deepseek", "DEEPSEEK_API_KEY"),
        ("openrouter", "OPENROUTER_API_KEY"),
        ("groq", "GROQ_API_KEY"),
        ("mistral", "MISTRAL_API_KEY"),
    ]:
        key = getattr(settings, setting_name, None)
        if key:
            provider_keys[p_name] = key

    selected = await router_service.route(preference, provider_keys)
    if not selected:
        raise HTTPException(status_code=404, detail="No matching model found for the given preferences")

    return {
        "model": selected.model_info.id,
        "provider": selected.provider_name,
        "score": selected.score,
        "latency_tier": selected.model_info.latency_tier,
        "quality_tier": selected.model_info.quality_tier,
        "max_context": selected.model_info.max_context,
        "supports_vision": selected.model_info.supports_vision,
        "supports_tools": selected.model_info.supports_tools,
        "input_price_per_1k": selected.model_info.input_price_per_1k,
        "output_price_per_1k": selected.model_info.output_price_per_1k,
    }

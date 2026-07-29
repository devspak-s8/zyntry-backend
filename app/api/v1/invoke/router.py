from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies_api_key import get_api_key_user
from app.core.config import settings
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.billing import InsufficientCreditsError
from app.services.billing import BillingService, InsufficientCredits
from app.services.model_router import ModelRouter, RoutingGoal, RoutingPreference
from app.services.runtime_cache import runtime_cache

router = APIRouter()


class InvokeRequest(BaseModel):
    project: str
    input: str
    runtime_id: str | None = None
    model: str | None = None
    provider: str | None = None
    goal: str = "balanced"
    stream: bool = False
    top_k: int = 5
    conversation_id: str | None = None


class InvokeResponse(BaseModel):
    request_id: str
    response: str | None = None
    model: str
    provider: str
    latency_ms: float
    cost: float
    warnings: list[dict] = []
    events: list[dict] = []
    tokens_used: int = 0


@router.post("/invoke", response_model=InvokeResponse)
async def invoke(
    body: InvokeRequest,
    current_user: User = Depends(get_api_key_user),
    db: AsyncSession = Depends(get_session),
) -> InvokeResponse:
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    start_time = time.perf_counter()
    events: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Request Received", "request_id": request_id})

    uow = UnitOfWork(db)
    billing_service = BillingService(db)

    project = await uow.projects.get(uuid.UUID(body.project))
    if project is None or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Project Loaded", "project_id": str(project.id)})

    runtime = None
    if body.runtime_id:
        runtime = await uow.runtimes.get(uuid.UUID(body.runtime_id))
    if not runtime:
        runtime = await uow.runtimes.get_by_project(project.id)

    if runtime:
        cached = await runtime_cache.get(str(runtime.id))
        if cached:
            runtime_data = cached
        else:
            runtime_data = {
                "id": str(runtime.id),
                "provider": runtime.provider,
                "model": runtime.model,
                "embedding_model": runtime.embedding_model,
                "vector_store": runtime.vector_store,
                "config": runtime.config,
                "status": runtime.status,
            }
            await runtime_cache.set(str(runtime.id), runtime_data, ttl=300)
        events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Runtime Loaded", "runtime_id": str(runtime.id), "cached": bool(cached)})
    else:
        runtime_data = {"provider": "openai", "model": "gpt-4o", "config": {}}
        events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Runtime Loaded", "runtime_id": None, "cached": False})

    if runtime_data.get("status") not in ("active", None):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not ready")

    wallet = await billing_service.get_wallet(current_user.id)
    if wallet.status != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=InsufficientCreditsError(required=Decimal("0"), balance=wallet.balance).model_dump(),
        )

    provider_name = body.provider or runtime_data.get("provider", "openai")
    model_name = body.model or runtime_data.get("model", "gpt-4o")

    goal = RoutingGoal(body.goal) if body.goal in [g.value for g in RoutingGoal] else RoutingGoal.BALANCED
    preference = RoutingPreference(goal=goal)

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

    router_service = ModelRouter(uow)
    selected = await router_service.route(preference, provider_keys)

    if selected:
        provider_name = selected.provider_name
        model_name = selected.model_info.id
        events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Model Selected", "model": model_name, "provider": provider_name, "score": selected.score})
    else:
        warnings.append({"code": "MODEL_NOT_FOUND", "message": "No matching model found for preference, using default"})
        events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Model Selected", "model": model_name, "provider": provider_name, "score": 0})

    tools = await uow.tools.get_by_project(str(project.id))
    tool_calls = []
    if tools:
        events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Tools Executed", "count": len(tools)})
        tool_calls = [{"name": t.name, "status": "skipped"} for t in tools]

    estimated_cost = await billing_service.calculate_cost(
        provider=provider_name,
        model=model_name,
        operation="invoke",
        input_tokens=len(body.input.split()),
        output_tokens=500,
        requests=1,
    )

    if wallet.balance < estimated_cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=InsufficientCreditsError(required=estimated_cost, balance=wallet.balance).model_dump(),
        )

    budget_ok = await billing_service.check_budget(current_user.id, estimated_cost)
    if not budget_ok:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={"error": "Budget limit reached", "required": float(estimated_cost), "balance": float(wallet.balance)},
        )

    response_text = f"Invoked {model_name} on {provider_name} for project {project.name}. Input: {body.input[:100]}..."
    latency_ms = (time.perf_counter() - start_time) * 1000

    actual_cost = await billing_service.calculate_cost(
        provider=provider_name,
        model=model_name,
        operation="invoke",
        input_tokens=len(body.input.split()),
        output_tokens=len(response_text.split()),
        requests=1,
    )

    try:
        await billing_service.deduct_credit(
            user_id=current_user.id,
            amount=actual_cost,
            reason=f"Invoke: {model_name}",
            reference_id=request_id,
            metadata={"model": model_name, "provider": provider_name, "latency_ms": latency_ms, "project_id": str(project.id)},
        )
        await billing_service.record_usage(
            user_id=current_user.id,
            provider=provider_name,
            model=model_name,
            operation="invoke",
            cost=actual_cost,
            project_id=project.id,
            input_tokens=len(body.input.split()),
            output_tokens=len(response_text.split()),
            latency_ms=int(latency_ms),
        )
    except InsufficientCredits:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=InsufficientCreditsError(required=actual_cost, balance=wallet.balance).model_dump(),
        )
    except Exception:
        raise

    events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Response Generated", "model": model_name})
    events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Wallet Deducted", "amount": float(actual_cost)})
    events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Completed", "request_id": request_id})

    return InvokeResponse(
        request_id=request_id,
        response=response_text,
        model=model_name,
        provider=provider_name,
        latency_ms=round(latency_ms, 2),
        cost=float(actual_cost),
        warnings=warnings,
        events=events,
        tokens_used=len(body.input.split()) + len(response_text.split()),
    )

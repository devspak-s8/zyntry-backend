from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.features.dependencies import require_api_key_feature
from app.core.config import settings
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.actions import ActionRequest, ActionResponse
from app.schemas.billing import InsufficientCreditsError
from app.services.actions.confirmations import ConfirmationService
from app.services.actions.executor import ActionExecutor
from app.services.actions.guardrails import GuardrailService as ActionGuardrailService
from app.services.billing import BillingService, InsufficientCredits
from app.services.metered_billing import InsufficientBalanceError, MeteredBillingService
from app.services.guardrails import GuardrailService
from app.services.model_router import ModelRouter, RoutingGoal, RoutingPreference
from app.services.oauth.service import OAuthService

router = APIRouter()
guardrail_service = GuardrailService()


def _normalize_runtime_status(status_val: Any) -> str | None:
    if status_val is None:
        return None
    try:
        return str(status_val).strip().lower()
    except Exception:
        return str(status_val)


def _is_runtime_ready(status_val: Any) -> bool:
    norm_status = _normalize_runtime_status(status_val)
    if norm_status is None:
        return True
    return norm_status not in {"failed", "cancelled"}


async def _charge_invoke_if_billable(
    billing_service: BillingService,
    *,
    user_id: uuid.UUID,
    amount: Decimal,
    reason: str,
    reference_id: str,
    metadata: dict[str, Any],
) -> None:
    """Do not create an invalid zero-value debit when pricing is not configured."""
    if amount <= Decimal("0"):
        return
    await billing_service.deduct_credit(
        user_id=user_id,
        amount=amount,
        reason=reason,
        reference_id=reference_id,
        metadata=metadata,
    )


def _catalog_token_cost(
    candidate: Any,
    *,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    if candidate is None:
        return Decimal("0")
    info = candidate.model_info
    input_rate = Decimal(str(info.input_price_per_1k or 0))
    output_rate = Decimal(str(info.output_price_per_1k or 0))
    cost = (
        input_rate * Decimal(input_tokens) / Decimal(1000)
        + output_rate * Decimal(output_tokens) / Decimal(1000)
    )
    if cost > 0:
        return max(cost, Decimal("0.0001"))
    return Decimal("0")


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
    idempotency_key: str | None = None
    json_schema: dict | None = None
    actions: list[ActionRequest] = []


class InvokeResponse(BaseModel):
    request_id: str
    response: str | None = None
    model: str
    provider: str
    latency_ms: float
    cost: float
    warnings: list[dict] = []
    events: list[dict] = []
    tool_calls: list[dict] = []
    action_results: list[ActionResponse] = []
    tokens_used: int = 0
    guardrail_violations: list[str] = []
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    remaining_balance: float | None = None


async def _execute_tool(tool: Any, arguments: dict) -> dict:
    impl = (tool.implementation or "").strip()
    if not impl:
        return {"name": tool.name, "status": "skipped", "reason": "no_implementation"}
    if impl.startswith("http://") or impl.startswith("https://"):
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(impl, json=arguments)
                return {"name": tool.name, "status": "success", "result": resp.json() if resp.headers.get("content-type") == "application/json" else resp.text, "status_code": resp.status_code}
        except Exception as exc:
            return {"name": tool.name, "status": "error", "error": str(exc)}
    if impl.startswith("webhook://"):
        url = impl[len("webhook://"):]
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(url, json=arguments)
                return {"name": tool.name, "status": "success", "result": resp.json() if resp.headers.get("content-type") == "application/json" else resp.text, "status_code": resp.status_code}
        except Exception as exc:
            return {"name": tool.name, "status": "error", "error": str(exc)}
    return {"name": tool.name, "status": "skipped", "reason": "unsupported_implementation"}


@router.post("/invoke", response_model=InvokeResponse)
async def invoke(
    body: InvokeRequest,
    request: Request,
    current_user: User = Depends(require_api_key_feature("runtime_console")),
    db: AsyncSession = Depends(get_session),
) -> InvokeResponse:
    request_id = f"req_{uuid.uuid4().hex[:12]}"
    start_time = time.perf_counter()
    events: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    tool_calls: list[dict[str, Any]] = []

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
        runtime_data = {
            "id": str(runtime.id),
            "provider": runtime.provider,
            "model": runtime.model,
            "embedding_model": runtime.embedding_model,
            "vector_store": runtime.vector_store,
            "config": runtime.config,
            "status": runtime.status,
        }
        events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Runtime Loaded", "runtime_id": str(runtime.id), "cached": False})
    else:
        runtime_data = {"provider": "openai", "model": "gpt-4o", "config": {}}
        events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Runtime Loaded", "runtime_id": None, "cached": False})

    status_val = runtime_data.get("status")
    if status_val is not None:
        norm_status = _normalize_runtime_status(status_val)
        if not _is_runtime_ready(status_val):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not ready")
        if norm_status and norm_status != "active":
            warnings.append({
                "code": "RUNTIME_STATUS",
                "message": f"Runtime status is {norm_status}; continuing with available configuration",
            })

    wallet = await billing_service.get_wallet(current_user.id)
    if wallet.status != "active":
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=InsufficientCreditsError(required=Decimal("0"), balance=wallet.balance).model_dump(),
        )

    provider_name = body.provider or runtime_data.get("provider", "openai")
    model_name = body.model or runtime_data.get("model", "gpt-4o")

    input_violations = guardrail_service.validate_input(body.input, body.json_schema)
    if input_violations:
        raise HTTPException(status_code=400, detail={"guardrail_violations": input_violations})

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
    ]:
        key = getattr(settings, setting_name, None)
        if key:
            provider_keys[p_name] = key

    # Reserve the worst-case inference estimate before contacting a provider.
    # A failed provider call releases this reservation without charging.
    pre_reservation = None
    billing_idempotency_key = body.idempotency_key or request_id
    estimated_cost = await billing_service.calculate_cost(
        provider=provider_name,
        model=model_name,
        operation="invoke",
        input_tokens=len(body.input.split()),
        output_tokens=2048,
        requests=1,
    )
    if estimated_cost > Decimal("0"):
        if wallet.balance < estimated_cost:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=InsufficientCreditsError(required=estimated_cost, balance=wallet.balance, available_balance=wallet.balance).model_dump(),
            )
        if not await billing_service.check_budget(current_user.id, estimated_cost):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={"error": "Budget limit reached", "required": float(estimated_cost), "balance": float(wallet.balance)},
            )
        try:
            pre_reservation = await MeteredBillingService(db).reserve(
                user_id=current_user.id,
                amount=estimated_cost,
                request_id=request_id,
                idempotency_key=billing_idempotency_key,
                organization_id=current_user.organization_id,
                project_id=project.id,
                runtime_id=uuid.UUID(body.runtime_id) if body.runtime_id else None,
                api_key_id=getattr(request.state, "api_key_id", None),
                resource_type="ai_inference",
                metadata={"estimate": True, "model": model_name, "provider": provider_name},
            )
        except (InsufficientBalanceError,):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=InsufficientCreditsError(required=estimated_cost, balance=wallet.balance, available_balance=wallet.balance).model_dump(),
            )

    router_service = ModelRouter(uow)
    messages = [{"role": "user", "content": body.input}]
    try:
        result_text, invoked_model, invoked_provider, last_error = await router_service._invoke_with_fallback(
            preference, provider_keys, messages
        )
    except Exception:
        if pre_reservation is not None:
            await MeteredBillingService(db).release(pre_reservation.id, reason="provider_exception")
        raise
    if not result_text:
        if pre_reservation is not None:
            await MeteredBillingService(db).release(pre_reservation.id, reason="provider_failed")
        raise HTTPException(status_code=502, detail=f"All providers failed: {last_error}")
    provider_name = invoked_provider or provider_name
    model_name = invoked_model or model_name
    events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Model Selected", "model": model_name, "provider": provider_name})
    if last_error:
        warnings.append({"code": "PROVIDER_FAILOVER", "message": last_error})

    tools = await uow.tools.get_by_project(str(project.id))
    if tools:
        for tool in tools:
            args = {"input": body.input, "project_id": str(project.id), "user_id": str(current_user.id)}
            result = await _execute_tool(tool, args)
            tool_calls.append(result)
            events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Tool Executed", "tool": tool.name, "status": result.get("status")})

    action_results: list[ActionResponse] = []
    if body.actions:
        action_executor = ActionExecutor(uow)
        confirmation_service = ConfirmationService(uow)
        try:
            await OAuthService(uow).pre_resolve_project_tokens(project.id)
        except Exception:
            pass

        for action_req in body.actions:
            action_req.project_id = str(project.id)
            valid, error = ActionGuardrailService.validate_action_arguments(
                action_req.provider, action_req.action, action_req.arguments,
            )
            if not valid:
                action_results.append(ActionResponse(success=False, error=error))
                continue

            risk_actions = {"delete", "remove", "archive", "merge", "close", "cancel", "expire", "revoke"}
            requires_confirmation = any(risk in action_req.action.lower() for risk in risk_actions)

            if requires_confirmation and not action_req.confirm:
                confirmation = await confirmation_service.request(
                    user_id=current_user.id,
                    project_id=project.id,
                    provider=action_req.provider,
                    action=action_req.action,
                    arguments=action_req.arguments,
                    risk="high" if any(d in action_req.action.lower() for d in ["delete", "remove", "archive"]) else "medium",
                )
                action_results.append(ActionResponse(
                    success=False,
                    error="Confirmation required",
                    requires_confirmation=True,
                    confirmation_id=str(confirmation.id),
                    confirmation_reason=f"Action '{action_req.action}' requires explicit confirmation",
                ))
                continue

            result = await action_executor.execute(action_req, current_user.id, project.id)
            action_results.append(result)
            events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Action Executed", "provider": action_req.provider, "action": action_req.action, "success": result.success})

    response_text, output_violations = guardrail_service.enforce(result_text, body.json_schema)
    latency_ms = (time.perf_counter() - start_time) * 1000

    metered = MeteredBillingService(db)
    billing_breakdown = await metered.pricing.calculate(
        provider_name,
        model_name,
        input_tokens=len(body.input.split()),
        output_tokens=len(response_text.split()),
        requests=0,
    )
    actual_cost = billing_breakdown["amount"]
    if actual_cost <= 0:
        actual_cost = _catalog_token_cost(
            router_service.last_invoked_candidate,
            input_tokens=len(body.input.split()),
            output_tokens=len(response_text.split()),
        )
        billing_breakdown["provider_cost"] = actual_cost
        billing_breakdown["markup"] = Decimal("0")

    reservation = pre_reservation
    try:
        if reservation is None and actual_cost > Decimal("0"):
            reservation = await metered.reserve(
                user_id=current_user.id,
                amount=actual_cost,
                request_id=request_id,
                idempotency_key=billing_idempotency_key,
                organization_id=current_user.organization_id,
                project_id=project.id,
                runtime_id=uuid.UUID(body.runtime_id) if body.runtime_id else None,
                api_key_id=getattr(request.state, "api_key_id", None),
                resource_type="ai_inference",
                metadata={"model": model_name, "provider": provider_name},
            )
        if reservation is not None:
            await metered.settle(
                reservation.id,
                actual_amount=actual_cost,
                provider_cost=billing_breakdown["provider_cost"],
                metadata={"model": model_name, "provider": provider_name, "latency_ms": latency_ms},
                transaction_type="AI_INFERENCE",
            )
        await billing_service.record_usage(
            user_id=current_user.id,
            provider=provider_name,
            model=model_name,
            operation="invoke",
            cost=actual_cost,
            project_id=project.id,
            organization_id=current_user.organization_id,
            runtime_id=uuid.UUID(body.runtime_id) if body.runtime_id else None,
            api_key_id=getattr(request.state, "api_key_id", None),
            request_id=request_id,
            input_tokens=len(body.input.split()),
            output_tokens=len(response_text.split()),
            latency_ms=int(latency_ms),
            provider_cost=billing_breakdown["provider_cost"],
            platform_markup=billing_breakdown["markup"],
        )
    except (InsufficientCredits, InsufficientBalanceError) as exc:
        if reservation is not None:
            await metered.release(reservation.id, reason="settlement_failed")
        required = getattr(exc, "required", actual_cost)
        available = getattr(exc, "available", wallet.balance)
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=InsufficientCreditsError(required=required, balance=available, available_balance=available).model_dump(),
        )
    except Exception:
        if reservation is not None:
            await metered.release(reservation.id, reason="billing_failed")
        raise

    try:
        await uow.request_logs.create(
            project_id=project.id,
            request_id=request_id,
            method="POST",
            endpoint="/invoke",
            status=200,
            latency_ms=int(latency_ms),
            tokens=len(body.input.split()) + len(response_text.split()),
            provider=provider_name,
            model=model_name,
            cost=int(actual_cost),
            started_at=datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            user_id=current_user.id,
            ip="",
        )
        await uow.commit()
    except Exception:
        pass

    events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Response Generated", "model": model_name})
    events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Wallet Deducted", "amount": float(actual_cost)})
    events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Completed", "request_id": request_id})

    wallet = await billing_service.get_wallet(current_user.id)
    return InvokeResponse(
        request_id=request_id,
        response=response_text,
        model=model_name,
        provider=provider_name,
        latency_ms=round(latency_ms, 2),
        cost=float(actual_cost),
        warnings=warnings,
        events=events,
        tool_calls=tool_calls,
        action_results=action_results,
        tokens_used=len(body.input.split()) + len(response_text.split()),
        guardrail_violations=output_violations,
        estimated_cost=float(estimated_cost),
        actual_cost=float(actual_cost),
        remaining_balance=float(wallet.balance),
    )

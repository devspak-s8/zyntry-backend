from __future__ import annotations

import time
import uuid
import logging
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, AsyncGenerator

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.features.dependencies import require_api_key_feature
from app.core.config import settings
from app.core.database import get_session
from app.models.users import User
from app.models.apikeys import ApiKey
from app.repositories import UnitOfWork
from app.schemas.actions import ActionRequest, ActionResponse
from app.schemas.billing import InsufficientCreditsError
from app.services.actions.confirmations import ConfirmationService
from app.services.actions.executor import ActionExecutor
from app.services.actions.guardrails import (
    GuardrailService as ActionGuardrailService,
    requires_action_confirmation,
)
from app.services.billing import BillingService, InsufficientCredits
from app.services.metered_billing import InsufficientBalanceError, MeteredBillingService
from app.services.guardrails import GuardrailService
from app.services.model_router import ModelRouter, RoutingGoal, RoutingPreference
from app.services.provider_credentials import resolve_provider_key
from app.services.oauth.service import OAuthService
from app.services.security.outbound import validate_outbound_url
from app.services.security.secrets import default_secret_manager
from app.services.runtime_security import (
    RuntimeSecurityService,
    RuntimeSecurityViolation,
    normalize_runtime_security_policy,
    persist_runtime_security_event,
    redact_pii,
)
from app.services.runtime_capabilities import (
    authorize_runtime_request,
    check_runtime_budget,
    join_source_records,
)
from app.schemas.capabilities import CrossSourceJoinRequest, SourceRecordSet

router = APIRouter()
guardrail_service = GuardrailService()
runtime_security_service = RuntimeSecurityService()
logger = logging.getLogger(__name__)


def _insufficient_credits_detail() -> dict[str, str]:
    return {
        "error": "Insufficient credits",
        "message": "Add credits to continue.",
    }


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
    actions: list[ActionRequest] = Field(default_factory=list)
    # Optional explicit read context.  When supplied, only these connected
    # tools are queried and their provenance is added to the model context.
    # This enables safe cross-source answers without invoking every connector
    # on every request.
    context_sources: list[str] = Field(default_factory=list, max_length=20)
    join_on: str | None = None


class InvokeResponse(BaseModel):
    request_id: str
    response: str | None = None
    model: str
    provider: str
    latency_ms: float
    cost: float
    warnings: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    action_results: list[ActionResponse] = Field(default_factory=list)
    source_context: dict[str, Any] | None = None
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
            url = validate_outbound_url(impl)
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                resp = await client.post(url, json=arguments)
                return {"name": tool.name, "status": "success", "result": resp.json() if resp.headers.get("content-type") == "application/json" else resp.text, "status_code": resp.status_code}
        except Exception as exc:
            return {"name": tool.name, "status": "error", "error": str(exc)}
    if impl.startswith("webhook://"):
        url = impl[len("webhook://"):]
        try:
            url = validate_outbound_url(url)
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                resp = await client.post(url, json=arguments)
                return {"name": tool.name, "status": "success", "result": resp.json() if resp.headers.get("content-type") == "application/json" else resp.text, "status_code": resp.status_code}
        except Exception as exc:
            return {"name": tool.name, "status": "error", "error": str(exc)}
    return {"name": tool.name, "status": "skipped", "reason": "unsupported_implementation"}


@router.post("/invoke/stream", response_model=None)
async def invoke_stream(
    body: InvokeRequest,
    request: Request,
    current_user: User = Depends(require_api_key_feature("runtime_console")),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream lifecycle progress and the final invoke result as SSE.

    Provider token streaming is exposed by ``/chat/completions``.  This
    endpoint gives API consumers a single runtime-console stream that also
    reports security, retrieval, routing, tool, and billing progress.
    """
    async def event_stream() -> AsyncGenerator[str, None]:
        yield f"data: {json.dumps({'event': 'Request Received', 'status': 'started'})}\n\n"
        result = await invoke(body.model_copy(update={"stream": False}), request, current_user, db)
        for event in result.events:
            yield f"data: {json.dumps(event, default=str)}\n\n"
        yield f"data: {json.dumps({'event': 'Completed', 'status': 'completed', 'result': result.model_dump()}, default=str)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/invoke", response_model=None)
async def invoke(
    body: InvokeRequest,
    request: Request,
    current_user: User = Depends(require_api_key_feature("runtime_console")),
    db: AsyncSession = Depends(get_session),
) -> InvokeResponse | StreamingResponse:
    if body.stream:
        return await invoke_stream(body, request, current_user, db)
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

    if runtime and runtime.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found for this project")

    api_key_id = getattr(request.state, "api_key_id", None)
    api_key = await db.get(ApiKey, api_key_id) if api_key_id else None
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    key_scopes = set(api_key.scopes or [])
    if "read" not in key_scopes and "*" not in key_scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key lacks read scope")
    if body.actions and "write" not in key_scopes and "*" not in key_scopes:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key lacks write scope")
    if api_key.project_id and api_key.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key is not authorized for this project")
    if api_key.runtime_id and (runtime is None or api_key.runtime_id != runtime.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key is not authorized for this runtime")

    access_role = "developer"
    if runtime:
        action_requires_write = False
        if body.actions:
            from app.services.actions.registry import ActionRegistry
            for action_request in body.actions:
                try:
                    definitions = ActionRegistry.list_actions(action_request.provider)
                except KeyError:
                    definitions = []
                definition = next((item for item in definitions if item.name == action_request.action), None)
                if requires_action_confirmation(action_request.action, definition):
                    action_requires_write = True
                    break
        try:
            access_role, _ = authorize_runtime_request(
                runtime,
                current_user,
                api_key_scopes=key_scopes,
                requires_write=action_requires_write,
                sources=body.context_sources or None,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc

    project_environment = str((project.settings or {}).get("environment") or "").strip().lower()
    runtime_environment = str(runtime.environment if runtime else project_environment or "development").strip().lower()
    if project_environment and project_environment != runtime_environment:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Project and runtime environments do not match")
    if str(api_key.environment or "development").strip().lower() != runtime_environment:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key environment does not match this runtime")

    if runtime:
        runtime_data = {
            "id": str(runtime.id),
            "provider": runtime.provider,
            "model": runtime.model,
            "routing_strategy": runtime.routing_strategy,
            "embedding_model": runtime.embedding_model,
            "vector_store": runtime.vector_store,
            "fallback_models": list(runtime.fallback_models or []),
            # Runtime configuration can contain legacy/generated credentials.
            # Invocation telemetry is user-visible, so never echo those
            # values even when a runtime predates the worker fix.
            "config": default_secret_manager.redact(runtime.config or {}),
            "status": runtime.status,
        }
        events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Runtime Loaded", "runtime_id": str(runtime.id), "cached": False})
        try:
            security_event = await runtime_security_service.enforce(runtime, request, body.input)
            events.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "Runtime Security Checked",
                "enabled": security_event.get("enabled", False),
            })
            try:
                await persist_runtime_security_event(
                    db,
                    runtime,
                    "checked",
                    request_id=request_id,
                    client_ip=security_event.get("client_ip"),
                    code="suspicious_request" if security_event.get("suspicious") else None,
                    message="Runtime request passed security checks.",
                )
            except Exception:
                logger.exception("Unable to persist runtime security check event")
        except RuntimeSecurityViolation as exc:
            events.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "Runtime Security Blocked",
                "code": exc.code,
            })
            try:
                await persist_runtime_security_event(
                    db,
                    runtime,
                    "blocked",
                    request_id=request_id,
                    client_ip=request.client.host if request.client else None,
                    code=exc.code,
                    message=exc.message,
                    status_code=exc.status_code,
                )
                await db.commit()
            except Exception:
                logger.exception("Unable to persist runtime security blocked event")
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc
    else:
        runtime_data = {"provider": "openai", "model": "gpt-4o", "config": {}}
        events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Runtime Loaded", "runtime_id": None, "cached": False})

    status_val = runtime_data.get("status")
    events.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "Runtime Access Evaluated",
        "role": access_role,
        "policy_enabled": bool(runtime and isinstance(runtime.config, dict) and (runtime.config or {}).get("access_control")),
    })
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
            detail=_insufficient_credits_detail(),
        )

    provider_name = body.provider or runtime_data.get("provider") or "openai"
    model_name = body.model or runtime_data.get("model") or "gpt-4o"
    dynamic_routing_enabled = bool((runtime_data.get("config") or {}).get("dynamic_routing_enabled"))
    explicit_model_selection = bool(body.provider or body.model)
    automatic_routing = dynamic_routing_enabled and not explicit_model_selection

    input_violations = guardrail_service.validate_input(body.input, body.json_schema)
    if input_violations:
        raise HTTPException(status_code=400, detail={"guardrail_violations": input_violations})

    configured_strategy = str(runtime_data.get("routing_strategy") or "").strip().lower()
    strategy_goal = {
        "latency_optimized": RoutingGoal.FASTEST,
        "quality_optimized": RoutingGoal.REASONING,
        "balanced": RoutingGoal.BALANCED,
    }.get(configured_strategy)
    # The request goal is an explicit per-call override. When callers leave it
    # at the default, use the runtime's saved routing strategy instead.
    goal = RoutingGoal(body.goal) if body.goal in [g.value for g in RoutingGoal] else (strategy_goal or RoutingGoal.BALANCED)
    if body.goal == "balanced" and strategy_goal:
        goal = strategy_goal
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
        ("meta", "META_API_KEY"),
        ("bedrock", "AWS_ACCESS_KEY_ID"),
    ]:
        if runtime:
            runtime_provider_key, _ = await resolve_provider_key(
                uow,
                p_name,
                project_id=project.id,
                organization_id=project.organization_id,
            )
            if runtime_provider_key:
                provider_keys[p_name] = runtime_provider_key
        key = getattr(settings, setting_name, None)
        if key and p_name not in provider_keys:
            provider_keys[p_name] = key

    events.append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": "Routing Mode",
        "mode": "automatic" if automatic_routing else "configured",
        "configured_provider": provider_name,
        "configured_model": model_name,
    })

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
    if runtime:
        budget_ok, budget_code, budget_policy = await check_runtime_budget(
            db, runtime, estimated_cost=estimated_cost
        )
        events.append({
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event": "Runtime Budget Checked",
            "enabled": bool(budget_policy.get("enabled")),
            "status": "allowed" if budget_ok else "blocked",
        })
        if not budget_ok:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS if budget_code == "request_rate_limit_exceeded" else status.HTTP_402_PAYMENT_REQUIRED,
                detail={"code": budget_code, "message": "Runtime usage budget exceeded", "policy": budget_policy},
            )
    if estimated_cost > Decimal("0"):
        if wallet.balance < estimated_cost:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=_insufficient_credits_detail(),
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
                runtime_id=runtime.id if runtime else None,
                api_key_id=getattr(request.state, "api_key_id", None),
                resource_type="ai_inference",
                metadata={"estimate": True, "model": model_name, "provider": provider_name},
            )
        except (InsufficientBalanceError,):
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=_insufficient_credits_detail(),
            )

    router_service = ModelRouter(uow)
    source_context: dict[str, Any] | None = None
    messages = [{"role": "user", "content": body.input}]
    tools = await uow.tools.get_by_project(str(project.id))
    if body.context_sources:
        requested_sources = {item.strip().lower() for item in body.context_sources if item.strip()}
        selected_tools = []
        for tool in tools:
            connection = (tool.schema or {}).get("_zyntry_connection", {}) if isinstance(tool.schema, dict) else {}
            connector = str(connection.get("connector") or "").strip().lower()
            candidates = {connector, tool.name.strip().lower().replace(" ", "_")}
            if requested_sources.intersection(candidates):
                selected_tools.append(tool)
        if not selected_tools:
            raise HTTPException(status_code=404, detail={"code": "sources_not_connected", "sources": sorted(requested_sources)})
        source_sets: list[SourceRecordSet] = []
        for tool in selected_tools:
            args = {"input": body.input, "project_id": str(project.id), "user_id": str(current_user.id)}
            result = await _execute_tool(tool, args)
            tool_calls.append(result)
            connection = (tool.schema or {}).get("_zyntry_connection", {}) if isinstance(tool.schema, dict) else {}
            source_name = str(connection.get("connector") or tool.name).strip().lower()
            raw_result = result.get("result")
            records = raw_result if isinstance(raw_result, list) else (raw_result.get("records", []) if isinstance(raw_result, dict) else [])
            if not isinstance(records, list):
                records = []
            source_sets.append(SourceRecordSet(source=source_name, records=[item for item in records if isinstance(item, dict)]))
            events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Source Retrieved", "source": source_name, "status": result.get("status")})
        if body.join_on:
            source_context = join_source_records(CrossSourceJoinRequest(sources=source_sets, join_on=body.join_on))
        else:
            source_context = {
                "sources": [item.source for item in source_sets],
                "records": [{"source": item.source, "records": item.records} for item in source_sets],
                "matched_records": sum(len(item.records) for item in source_sets),
                "join_on": None,
            }
        messages.insert(0, {
            "role": "system",
            "content": "Use the following connected internal source context first. Preserve source names and do not infer records that are not present.\n" + json.dumps(source_context, default=str),
        })
        events.append({"timestamp": datetime.now(timezone.utc).isoformat(), "event": "Cross-Source Context Assembled", "sources": source_context.get("sources", []), "matched_records": source_context.get("matched_records", 0)})
    try:
        if automatic_routing:
            result_text, invoked_model, invoked_provider, last_error = await router_service._invoke_with_fallback(
                preference, provider_keys, messages
            )
        else:
            configured_models = [model_name, *(runtime_data.get("fallback_models") or [])]
            result_text, invoked_model, invoked_provider, last_error = await router_service.invoke_fixed(
                provider_name,
                configured_models,
                provider_keys,
                messages,
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

    if tools and not body.context_sources:
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

            from app.services.actions.registry import ActionRegistry
            try:
                provider_actions = ActionRegistry.list_actions(action_req.provider)
            except KeyError:
                provider_actions = []
            action_definition = next(
                (
                    definition
                    for definition in provider_actions
                    if definition.name == action_req.action
                ),
                None,
            )
            requires_confirmation = requires_action_confirmation(
                action_req.action,
                action_definition,
            )

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
    if runtime:
        security_policy = normalize_runtime_security_policy(runtime.security_policies)
        if security_policy["pii_redaction"]:
            redacted_response = redact_pii(response_text)
            if redacted_response != response_text:
                response_text = redacted_response
                events.append({
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event": "Runtime PII Redacted",
                })
                try:
                    await persist_runtime_security_event(
                        db,
                        runtime,
                        "pii_redacted",
                        request_id=request_id,
                        message="PII was redacted from the runtime response.",
                        pii_redacted=True,
                    )
                except Exception:
                    logger.exception("Unable to persist runtime PII redaction event")
            # Tool and action payloads are part of the JSON response too. Keep
            # their shape intact while masking any PII returned by a connector.
            tool_calls = redact_pii(tool_calls)
            if source_context is not None:
                source_context = redact_pii(source_context)
            action_results = [
                ActionResponse.model_validate(redact_pii(item.model_dump()))
                for item in action_results
            ]
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
                runtime_id=runtime.id if runtime else None,
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
            runtime_id=runtime.id if runtime else None,
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
            detail=_insufficient_credits_detail(),
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
        source_context=source_context,
    )

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.features.dependencies import require_api_key_feature
from app.core.config import settings
from app.core.database import get_session
from app.models.apikeys import ApiKey
from app.models.events import Event
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.actions import ActionResponse
from app.schemas.capabilities import CrossSourceJoinRequest, SourceRecordSet
from app.services.actions.confirmations import ConfirmationService
from app.services.actions.executor import ActionExecutor
from app.services.actions.guardrails import (
    GuardrailService as ActionGuardrailService,
)
from app.services.actions.guardrails import (
    requires_action_confirmation,
)
from app.services.billing import BillingService, InsufficientCredits
from app.services.context_manager import ContextManager
from app.services.guardrails import GuardrailService
from app.services.invoke_support import (
    InvokeRequest,
    InvokeResponse,
)
from app.services.invoke_support import (
    catalog_token_cost as _catalog_token_cost,
)
from app.services.invoke_support import (
    charge_invoke_if_billable as _charge_invoke_if_billable,  # noqa: F401 - public test compatibility
)
from app.services.invoke_support import (
    execute_tool as _execute_tool,
)
from app.services.invoke_support import (
    insufficient_credits_detail as _insufficient_credits_detail,
)
from app.services.invoke_support import (
    is_runtime_ready as _is_runtime_ready,
)
from app.services.invoke_support import (
    load_recent_conversation_messages as _load_recent_conversation_messages,
)
from app.services.invoke_support import (
    normalize_runtime_status as _normalize_runtime_status,
)
from app.services.invoke_support import (
    tool_is_read_only as _tool_is_read_only,
)
from app.services.metered_billing import InsufficientBalanceError, MeteredBillingService
from app.services.model_router import ModelRouter, RoutingGoal, RoutingPreference
from app.services.oauth.service import OAuthService
from app.services.provider_credentials import resolve_provider_key
from app.services.runtime_capabilities import (
    authorize_runtime_request,
    check_runtime_budget,
    join_source_records,
)
from app.services.runtime_security import (
    RuntimeSecurityService,
    RuntimeSecurityViolation,
    normalize_runtime_security_policy,
    persist_runtime_security_event,
    redact_pii,
)
from app.services.security.secrets import default_secret_manager
from app.services.token_engine import CompletionUsage, TokenEngine

router = APIRouter()
guardrail_service = GuardrailService()
runtime_security_service = RuntimeSecurityService()
logger = logging.getLogger(__name__)


@router.post("/invoke/stream", response_model=None)
async def invoke_stream(
    body: InvokeRequest,
    request: Request,
    current_user: User = Depends(require_api_key_feature("runtime_console")),
    db: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Stream provider output plus lifecycle progress as SSE.

    The invoke pipeline still performs billing and persistence once, in the
    background task.  Provider adapters emit chunks through a queue so the
    client receives tokens as they arrive, followed by the same structured
    final response used by non-streaming callers.
    """
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    holder: dict[str, Any] = {"result": None, "error": None}

    async def on_token(token: str) -> None:
        await queue.put({"event": "Token", "token": token})

    async def run_invoke() -> None:
        request.state.invoke_stream_callback = on_token
        try:
            holder["result"] = await invoke(
                body.model_copy(update={"stream": False}),
                request,
                current_user,
                db,
            )
        except Exception as exc:  # pragma: no cover - exercised by clients
            logger.exception("Streaming runtime invocation failed")
            holder["error"] = exc
        finally:
            await queue.put(None)

    async def event_stream() -> AsyncGenerator[str]:
        yield f"data: {json.dumps({'event': 'Request Received', 'status': 'started'})}\n\n"
        task = asyncio.create_task(run_invoke())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item, default=str)}\n\n"
            await task
        finally:
            if not task.done():
                task.cancel()
        if holder["error"] is not None:
            yield f"data: {json.dumps({'event': 'Failed', 'status': 'failed', 'message': 'Runtime invocation failed. Check the execution log for details.'})}\n\n"
            return
        result = holder["result"]
        if result is None:
            yield f"data: {json.dumps({'event': 'Failed', 'status': 'failed', 'message': 'Invocation returned no result'})}\n\n"
            return
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

    events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Request Received", "request_id": request_id})

    uow = UnitOfWork(db)
    billing_service = BillingService(db)

    api_key_id = getattr(request.state, "api_key_id", None)
    api_key = await db.get(ApiKey, api_key_id) if api_key_id else None
    if api_key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    project_uuid: uuid.UUID | None = None
    if body.project:
        try:
            project_uuid = uuid.UUID(body.project)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid project ID") from exc
    elif api_key.project_id:
        project_uuid = api_key.project_id

    runtime_uuid: uuid.UUID | None = None
    if body.runtime_id:
        try:
            runtime_uuid = uuid.UUID(body.runtime_id)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid runtime ID") from exc
    elif api_key.runtime_id:
        runtime_uuid = api_key.runtime_id

    # Runtime-scoped keys can infer their project when the runtime is already
    # attached.  Unattached runtimes cannot be invoked until they are bound to
    # a project, which is enforced by the same readiness checks below.
    inferred_runtime = await uow.runtimes.get(runtime_uuid) if runtime_uuid else None
    if project_uuid is None and inferred_runtime is not None:
        project_uuid = inferred_runtime.project_id
    if project_uuid is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="API key is not scoped to a project; provide project in the request",
        )

    project = await uow.projects.get(project_uuid)
    if project is None or project.organization_id != current_user.organization_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Project Loaded", "project_id": str(project.id)})

    runtime = inferred_runtime
    if runtime is None and runtime_uuid:
        runtime = await uow.runtimes.get(runtime_uuid)
    if not runtime:
        runtime = await uow.runtimes.get_by_project(project.id)

    if runtime and runtime.project_id != project.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Runtime not found for this project")

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
        events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Runtime Loaded", "runtime_id": str(runtime.id), "cached": False})
        try:
            security_event = await runtime_security_service.enforce(runtime, request, body.input)
            events.append({
                "timestamp": datetime.now(UTC).isoformat(),
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
                "timestamp": datetime.now(UTC).isoformat(),
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
        events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Runtime Loaded", "runtime_id": None, "cached": False})

    status_val = runtime_data.get("status")
    events.append({
        "timestamp": datetime.now(UTC).isoformat(),
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
    context_manager = ContextManager()
    requested_output_tokens = int(
        body.max_tokens or (runtime_data.get("config") or {}).get("max_tokens") or 2_048
    )
    conversation_messages = await _load_recent_conversation_messages(
        db,
        body.conversation_id,
        project_id=project.id,
        user_id=current_user.id,
    )
    base_messages = [*conversation_messages, {"role": "user", "content": body.input}]
    preflight_input_tokens = context_manager.estimate_messages(base_messages)

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
        "timestamp": datetime.now(UTC).isoformat(),
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
        input_tokens=preflight_input_tokens,
        output_tokens=requested_output_tokens,
        requests=1,
    )
    if runtime:
        budget_ok, budget_code, budget_policy = await check_runtime_budget(
            db, runtime, estimated_cost=estimated_cost
        )
        events.append({
            "timestamp": datetime.now(UTC).isoformat(),
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
        except InsufficientBalanceError as exc:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=_insufficient_credits_detail(),
            ) from exc

    router_service = ModelRouter(uow)
    source_context: dict[str, Any] | None = None
    messages = base_messages
    tools = await uow.tools.get_by_project(project.id)
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
            events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Source Retrieved", "source": source_name, "status": result.get("status")})
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
        events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Cross-Source Context Assembled", "sources": source_context.get("sources", []), "matched_records": source_context.get("matched_records", 0)})

    # A preflight requirement lets automatic routing exclude models that cannot
    # hold this request plus a safe output reserve.  The final assembly then
    # trims/compresses only when the selected model actually needs it.
    raw_context_tokens = context_manager.estimate_messages(messages)
    preflight_required_context = raw_context_tokens + requested_output_tokens + 4_096
    preference.required_context_tokens = preflight_required_context
    assembly = context_manager.assemble(
        messages,
        provider=provider_name,
        model=model_name,
        requested_output_tokens=requested_output_tokens,
    )
    messages = assembly.messages
    events.append({
        "timestamp": datetime.now(UTC).isoformat(),
        "event": "Context Budgeted",
        **assembly.as_dict(),
    })
    warnings.extend({"code": "CONTEXT_OPTIMIZED", "message": item} for item in assembly.warnings)
    stream_callback = getattr(request.state, "invoke_stream_callback", None)
    # A streamed token can contain only half of an email, phone number, or
    # other identifier.  Do not emit partial unredacted data when the runtime
    # has live PII redaction enabled; the completed response is redacted below
    # and returned in the final SSE event instead.
    if runtime and normalize_runtime_security_policy(runtime.security_policies)["pii_redaction"]:
        if stream_callback is not None:
            events.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "Token Stream Buffered",
                "reason": "pii_redaction",
            })
        stream_callback = None

    # Keep every model attempt in the execution record.  ModelRouter resets
    # its per-call attempt list before each invocation, so the invoke pipeline
    # owns the aggregate when a tool follow-up model call is performed.
    model_attempts: list[dict[str, Any]] = []
    raw_config = runtime_data.get("config")
    config: dict[str, Any] = dict(raw_config) if isinstance(raw_config, dict) else {}
    autonomous_tool_loop = bool(config.get("autonomous_tool_loop", True))
    try:
        max_tool_steps = min(3, max(0, int(config.get("max_tool_steps", 3))))
    except (TypeError, ValueError):
        max_tool_steps = 1
    # Never let a write action be inferred from a read-only tool loop.  The
    # explicit action list below remains the only path for mutations.
    if body.actions:
        autonomous_tool_loop = False
    potential_tool_loop = (
        autonomous_tool_loop
        and max_tool_steps > 0
        and not body.context_sources
        and any(_tool_is_read_only(tool) for tool in tools)
    )
    initial_stream_callback = None if potential_tool_loop else stream_callback
    try:
        if automatic_routing:
            result_text, invoked_model, invoked_provider, last_error = await router_service._invoke_with_fallback(
                preference,
                provider_keys,
                messages,
                max_tokens=assembly.budget.reserved_output,
                on_token=initial_stream_callback,
            )
        else:
            configured_models = [model_name, *(runtime_data.get("fallback_models") or [])]
            result_text, invoked_model, invoked_provider, last_error = await router_service.invoke_fixed(
                provider_name,
                configured_models,
                provider_keys,
                messages,
                max_tokens=assembly.budget.reserved_output,
                on_token=initial_stream_callback,
            )
        model_attempts.extend(dict(item) for item in router_service.last_attempts)
    except Exception:
        if pre_reservation is not None:
            await MeteredBillingService(db).release(pre_reservation.id, reason="provider_exception")
        raise
    if not result_text:
        if pre_reservation is not None:
            await MeteredBillingService(db).release(pre_reservation.id, reason="provider_failed")
        logger.warning(
            "All configured providers failed",
            extra={"request_id": request_id, "provider_error": last_error[:500]},
        )
        raise HTTPException(
            status_code=502,
            detail="All configured providers failed. Check the execution log for details.",
        )
    provider_name = invoked_provider or provider_name
    model_name = invoked_model or model_name
    events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Model Selected", "model": model_name, "provider": provider_name})
    if router_service.last_routing_reason:
        events.append({
            "timestamp": datetime.now(UTC).isoformat(),
            "event": "Routing Decision",
            "reason": router_service.last_routing_reason,
        })
    if last_error:
        warnings.append({"code": "PROVIDER_FAILOVER", "message": last_error})

    automatic_tool_results: list[dict[str, Any]] = []
    completed_tool_steps = 0
    if autonomous_tool_loop and max_tool_steps > 0 and tools and not body.context_sources:
        # Run a bounded, sequential read-only loop. Each verified result is
        # fed back to the model before the next connector is called, so a
        # runtime can retrieve from several sources and refine its answer.
        # Write-capable tools never enter this loop and must use ``actions``.
        read_only_tools = [tool for tool in tools if _tool_is_read_only(tool)]
        for tool in tools:
            if _tool_is_read_only(tool):
                continue
            result = {
                "name": tool.name,
                "status": "skipped",
                "reason": "write_tool_requires_explicit_action",
            }
            tool_calls.append(result)
            events.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "Tool Skipped",
                "tool": tool.name,
                "reason": result["reason"],
            })

        for step, tool in enumerate(read_only_tools[:max_tool_steps], start=1):
            args = {"input": body.input, "project_id": str(project.id), "user_id": str(current_user.id)}
            result = await _execute_tool(tool, args)
            tool_calls.append(result)
            automatic_tool_results.append(result)
            completed_tool_steps = step
            events.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "Tool Executed",
                "tool": tool.name,
                "status": result.get("status"),
                "step": step,
            })

            # Every round is a model/tool boundary. Only the final planned
            # round streams tokens to avoid showing intermediate drafts.
            tool_context = {
                "tool_results": [
                    {
                        "name": item.get("name"),
                        "status": item.get("status"),
                        "result": item.get("result"),
                        "error": item.get("error"),
                    }
                    for item in automatic_tool_results
                ],
                "instruction": "Use only these verified tool results. If they are empty or failed, say so plainly; do not invent records.",
            }
            followup_messages = [
                *messages,
                {"role": "assistant", "content": result_text},
                {"role": "system", "content": "Verified read-only tool results:\n" + json.dumps(tool_context, default=str)},
                {"role": "user", "content": "Produce the best current answer using the verified tool results and the original request. More verified sources may be added in a later step."},
            ]
            followup_assembly = context_manager.assemble(
                followup_messages,
                provider=provider_name,
                model=model_name,
                requested_output_tokens=assembly.budget.reserved_output,
            )
            followup_estimate = await billing_service.calculate_cost(
                provider=provider_name,
                model=model_name,
                operation="invoke",
                input_tokens=followup_assembly.estimated_input_tokens,
                output_tokens=followup_assembly.budget.reserved_output,
                requests=1,
            )
            followup_allowed = True
            if runtime:
                followup_allowed, _, _ = await check_runtime_budget(
                    db, runtime, estimated_cost=followup_estimate
                )
            if not followup_allowed:
                warnings.append({
                    "code": "TOOL_LOOP_BUDGET",
                    "message": "A verified tool result was collected, but the runtime budget stopped the next synthesis step.",
                })
                break
            events.append({
                "timestamp": datetime.now(UTC).isoformat(),
                "event": "Tool Loop Synthesis",
                "step": step,
                "tool": tool.name,
                "tool_count": len(automatic_tool_results),
            })
            is_final_round = step >= min(max_tool_steps, len(read_only_tools))
            followup_text, followup_model, followup_provider, followup_error = await router_service.invoke_fixed(
                provider_name,
                [model_name],
                provider_keys,
                followup_assembly.messages,
                max_tokens=followup_assembly.budget.reserved_output,
                on_token=stream_callback if is_final_round else None,
            )
            model_attempts.extend(dict(item) for item in router_service.last_attempts)
            if followup_text:
                result_text = followup_text
                invoked_model = followup_model or invoked_model
                invoked_provider = followup_provider or invoked_provider
                provider_name = invoked_provider or provider_name
                model_name = invoked_model or model_name
            elif followup_error:
                warnings.append({
                    "code": "TOOL_LOOP_FALLBACK",
                    "message": "A tool result was retrieved, but synthesis failed; returning the last verified response.",
                })
                break

    action_results: list[ActionResponse] = []
    if body.actions:
        action_executor = ActionExecutor(uow)
        confirmation_service = ConfirmationService(uow)
        try:
            await OAuthService(uow).pre_resolve_project_tokens(project.id)
        except Exception:
            # Token pre-resolution is an optimization; action execution still
            # performs its own authorization. Keep failures observable without
            # exposing connector details to the caller.
            logger.exception(
                "Unable to pre-resolve project OAuth tokens",
                extra={"request_id": request_id, "project_id": str(project.id)},
            )

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

            action_result = await action_executor.execute(
                action_req, current_user.id, project.id
            )
            action_results.append(action_result)
            events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Action Executed", "provider": action_req.provider, "action": action_req.action, "success": action_result.success})

    response_text, output_violations = guardrail_service.enforce(result_text, body.json_schema)
    if runtime:
        security_policy = normalize_runtime_security_policy(runtime.security_policies)
        if security_policy["pii_redaction"]:
            redacted_response = redact_pii(response_text)
            if redacted_response != response_text:
                response_text = redacted_response
                events.append({
                    "timestamp": datetime.now(UTC).isoformat(),
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

    call_usages: list[CompletionUsage] = []
    for attempt in model_attempts or router_service.last_attempts:
        payload = attempt.get("usage")
        if isinstance(payload, dict):
            try:
                call_usages.append(
                    CompletionUsage(
                        input_tokens=int(payload.get("input_tokens", 0) or 0),
                        output_tokens=int(payload.get("output_tokens", 0) or 0),
                        cached_tokens=int(payload.get("cached_tokens", 0) or 0),
                        source=str(payload.get("source") or "estimated"),
                    )
                )
            except (TypeError, ValueError):
                continue
    usage = TokenEngine.aggregate(call_usages) if call_usages else (
        router_service.last_usage or CompletionUsage(
            input_tokens=assembly.estimated_input_tokens,
            output_tokens=TokenEngine.estimate_text(response_text),
        )
    )
    execution = {
        "model_call_count": len(call_usages),
        "model_calls": model_attempts or router_service.last_attempts,
        "tool_loop_enabled": bool(autonomous_tool_loop),
        "tool_loop_steps": completed_tool_steps,
        "tool_count": len(tool_calls),
        "total_tokens": usage.total_tokens,
        "usage_source": usage.source,
    }
    input_tokens = max(0, usage.input_tokens)
    output_tokens = max(0, usage.output_tokens)
    cached_tokens = max(0, usage.cached_tokens)

    metered = MeteredBillingService(db)
    billing_breakdown = await metered.pricing.calculate(
        provider_name,
        model_name,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
        requests=0,
    )
    actual_cost = billing_breakdown["amount"]
    if actual_cost <= 0:
        actual_cost = _catalog_token_cost(
            router_service.last_invoked_candidate,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
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
                metadata={
                    "model": model_name,
                    "provider": provider_name,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "context": assembly.as_dict(),
                },
            )
        if reservation is not None:
            await metered.settle(
                reservation.id,
                actual_amount=actual_cost,
                provider_cost=billing_breakdown["provider_cost"],
                metadata={
                    "model": model_name,
                    "provider": provider_name,
                    "latency_ms": latency_ms,
                    "usage_source": usage.source,
                    "context": assembly.as_dict(),
                },
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
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_tokens=cached_tokens,
            latency_ms=int(latency_ms),
            provider_cost=billing_breakdown["provider_cost"],
            platform_markup=billing_breakdown["markup"],
            metadata={
                "usage_source": usage.source,
                "routing_mode": "automatic" if automatic_routing else "configured",
                "routing_reason": router_service.last_routing_reason,
                "context": assembly.as_dict(),
                "fallback_models": list(runtime_data.get("fallback_models") or []),
            },
        )
    except (InsufficientCredits, InsufficientBalanceError) as exc:
        if reservation is not None:
            await metered.release(reservation.id, reason="settlement_failed")
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=_insufficient_credits_detail(),
        ) from exc
    except Exception:
        if reservation is not None:
            await metered.release(reservation.id, reason="billing_failed")
        raise

    # Keep one redacted, structured execution record in the tenant event
    # stream.  The request itself is never persisted here; only telemetry
    # needed for trace inspection and billing reconciliation is stored.
    db.add(
        Event(
            project_id=project.id,
            organization_id=project.organization_id,
            event_type="runtime.execution.completed",
            data={
                "request_id": request_id,
                "runtime_id": str(runtime.id) if runtime else None,
                "model": model_name,
                "provider": provider_name,
                "routing_mode": "automatic" if automatic_routing else "configured",
                "routing_reason": router_service.last_routing_reason,
                "usage": usage.as_dict(),
                "context": assembly.as_dict(),
                "latency_ms": round(latency_ms, 2),
                "cost": float(actual_cost),
                "warnings": warnings,
                "tool_count": len(tool_calls),
                "action_count": len(action_results),
                "execution": execution,
            },
        )
    )

    try:
        await uow.request_logs.create(
            project_id=project.id,
            request_id=request_id,
            method="POST",
            endpoint="/invoke",
            status=200,
            latency_ms=int(latency_ms),
            tokens=input_tokens + output_tokens,
            provider=provider_name,
            model=model_name,
            cost=int(actual_cost),
            started_at=datetime.fromtimestamp(start_time, tz=UTC).isoformat(),
            completed_at=datetime.now(UTC).isoformat(),
            user_id=current_user.id,
            ip="",
        )
        await uow.commit()
    except Exception:
        # Telemetry persistence must not turn a completed invocation into a
        # client-visible failure, but it must remain visible to operators.
        logger.exception("Unable to persist invocation event", extra={"request_id": request_id})

    events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Response Generated", "model": model_name})
    events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Wallet Deducted", "amount": float(actual_cost)})
    events.append({"timestamp": datetime.now(UTC).isoformat(), "event": "Completed", "request_id": request_id})

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
        tokens_used=input_tokens + output_tokens,
        guardrail_violations=output_violations,
        estimated_cost=float(estimated_cost),
        actual_cost=float(actual_cost),
        remaining_balance=float(wallet.balance),
        source_context=source_context,
        usage={
            **usage.as_dict(),
            "provider": provider_name,
            "model": model_name,
            "latency_ms": round(latency_ms, 2),
            "estimated_cost": float(estimated_cost),
            "actual_cost": float(actual_cost),
        },
        context=assembly.as_dict(),
        execution=execution,
    )

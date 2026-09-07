from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_project_membership, require_runtime_access
from app.core.config import settings
from app.core.database import get_session
from app.models.users import User
from app.models.billing import TransactionType
from app.models.events import Event
from app.repositories import UnitOfWork
from app.schemas.rag import RAGQuery, RAGResponse
from app.services.billing import BillingService
from app.services.guardrails import GuardrailService
from app.services.model_router import ModelRouter, RoutingGoal, RoutingPreference
from app.services.provider_credentials import resolve_provider_key
from app.services.rag import RAGPipeline, get_llm_provider
from app.services.runtime_capabilities import authorize_runtime_request, check_runtime_budget
from app.services.runtime_security import (
    RuntimeSecurityService,
    RuntimeSecurityViolation,
    normalize_runtime_security_policy,
    redact_pii,
)
from app.services.token_engine import TokenEngine

router = APIRouter()
guardrail_service = GuardrailService()
runtime_security_service = RuntimeSecurityService()


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[dict]
    stream: bool = False
    project_id: str | None = None
    runtime_id: str | None = None
    top_k: int = 5
    filters: dict | None = None
    conversation_id: str | None = None
    provider: str = "openai"
    json_schema: dict | None = None


class ChatCompletionChoice(BaseModel):
    index: int
    message: dict
    finish_reason: str


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[ChatCompletionChoice]
    usage: dict | None = None
    guardrail_violations: list[str] = []


@router.post("/completions", response_model=None)
async def chat_completions(
    body: ChatCompletionRequest,
    request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> ChatCompletionResponse | StreamingResponse:
    question = body.messages[-1].get("content", "") if body.messages else ""
    project_id = body.project_id or ""
    if not project_id:
        raise HTTPException(status_code=400, detail="project_id is required for RAG")
    project = await require_project_membership(project_id, current_user, db)
    runtime = None
    if body.runtime_id:
        runtime = await require_runtime_access(body.runtime_id, current_user, db)
        if runtime.project_id != project.id:
            raise HTTPException(status_code=404, detail="Runtime not found for this project")
        try:
            authorize_runtime_request(runtime, current_user)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        try:
            await runtime_security_service.enforce(runtime, request, question)
        except RuntimeSecurityViolation as exc:
            raise HTTPException(
                status_code=exc.status_code,
                detail={"code": exc.code, "message": exc.message},
            ) from exc

    input_violations = guardrail_service.validate_input(question, body.json_schema)
    if input_violations:
        raise HTTPException(status_code=400, detail={"guardrail_violations": input_violations})

    uow = UnitOfWork(db)
    effective_provider = body.provider
    effective_model = body.model
    selected_llm_provider = None
    routing_reason: str | None = None
    dynamic_chat_routing = bool(
        runtime
        and (runtime.config or {}).get("dynamic_routing_enabled")
        and body.model.strip().lower() in {"auto", "automatic", "dynamic"}
    )
    if dynamic_chat_routing:
        provider_keys: dict[str, str] = {}
        for provider_name, setting_name in (
            ("openai", "OPENAI_API_KEY"),
            ("anthropic", "ANTHROPIC_API_KEY"),
        ):
            runtime_key, _ = await resolve_provider_key(
                uow,
                provider_name,
                project_id=project.id,
                organization_id=project.organization_id,
            )
            provider_keys[provider_name] = runtime_key or getattr(settings, setting_name, None) or ""
        provider_keys = {name: key for name, key in provider_keys.items() if key}
        strategy = str(runtime.routing_strategy or "balanced").strip().lower()
        goal = {
            "latency_optimized": RoutingGoal.FASTEST,
            "quality_optimized": RoutingGoal.REASONING,
            "balanced": RoutingGoal.BALANCED,
        }.get(strategy, RoutingGoal.BALANCED)
        preference = RoutingPreference(goal=goal)
        preferred_provider = body.provider.strip().lower()
        if preferred_provider not in {"", "auto", "automatic", "dynamic"}:
            preference.preferred_providers = [preferred_provider]
        chat_router = ModelRouter(uow)
        candidate = await chat_router.route(preference, provider_keys)
        if candidate is not None:
            effective_provider = candidate.provider_name
            effective_model = candidate.model_info.id
            routing_reason = chat_router.last_routing_reason
            try:
                selected_llm_provider = get_llm_provider(
                    effective_provider,
                    provider_keys[effective_provider],
                )
            except (KeyError, ValueError):
                selected_llm_provider = None
        else:
            # Preserve a useful configured fallback if discovery is unavailable.
            effective_provider = runtime.provider or body.provider or "openai"
            effective_model = runtime.model or "gpt-4o"

    body = body.model_copy(update={"provider": effective_provider, "model": effective_model})
    rag_query = RAGQuery(
        question=question,
        project_id=project_id,
        user_id=str(current_user.id),
        runtime_id=body.runtime_id,
        top_k=body.top_k,
        filters=body.filters,
        stream=body.stream,
        conversation_id=body.conversation_id,
        model=effective_model,
        provider=effective_provider,
    )

    pipeline = RAGPipeline(uow=uow, llm_provider=selected_llm_provider)
    billing_service = BillingService(db)

    project_uuid = uuid.UUID(project_id)
    runtime_uuid = uuid.UUID(body.runtime_id) if body.runtime_id else None
    request_id = str(uuid.uuid4())
    estimated_cost = await billing_service.calculate_cost(
        provider=body.provider,
        model=body.model,
        operation="chat",
        input_tokens=TokenEngine.estimate_text(question),
        output_tokens=2_048,
        vector_searches=max(1, body.top_k),
        requests=1,
    )
    if runtime:
        budget_ok, budget_code, budget_policy = await check_runtime_budget(
            db, runtime, estimated_cost=estimated_cost
        )
        if not budget_ok:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS if budget_code == "request_rate_limit_exceeded" else status.HTTP_402_PAYMENT_REQUIRED,
                detail={"code": budget_code, "message": "Runtime usage budget exceeded", "policy": budget_policy},
            )

    wallet = await billing_service.get_wallet(current_user.id)
    if wallet.status != "active" or wallet.balance < estimated_cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Insufficient Credits",
                "required": float(estimated_cost),
                "balance": float(wallet.balance),
            },
        )

    budget_ok = await billing_service.check_budget(current_user.id, estimated_cost)
    if not budget_ok:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Budget limit reached",
                "required": float(estimated_cost),
                "balance": float(wallet.balance),
            },
        )

    start_time = time.perf_counter()
    try:
        reservation = await billing_service.reserve(
            user_id=current_user.id,
            amount=estimated_cost,
            request_id=request_id,
            idempotency_key=f"chat:{request_id}",
            organization_id=current_user.organization_id,
            project_id=project_uuid,
            runtime_id=runtime_uuid,
            resource_type="rag_chat",
            metadata={"model": body.model, "provider": body.provider, "top_k": body.top_k},
        )
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=str(exc)) from exc

    if body.stream:
        full_answer = ""
        buffer_output_for_redaction = bool(
            runtime
            and normalize_runtime_security_policy(runtime.security_policies)["pii_redaction"]
        )

        async def sse_generator() -> AsyncGenerator[str, None]:
            nonlocal full_answer
            source_count = 0
            rerank_items = 0
            provider_usage: dict | None = None
            try:
                result = await pipeline.query(rag_query)
                if hasattr(result, "__anext__"):
                    async for chunk in result:
                        payload = json.loads(chunk) if isinstance(chunk, str) else chunk
                        full_answer += payload.get("token", "")
                        source_count = max(source_count, len(payload.get("sources", [])))
                        rerank_items = max(rerank_items, int(payload.get("rerank_items", 0) or 0))
                        if isinstance(payload.get("usage"), dict):
                            provider_usage = payload["usage"]
                        # A token can contain only half of an email/phone/card
                        # pattern. Buffer content while live PII redaction is
                        # enabled so sensitive text is never emitted before
                        # the complete answer can be sanitized.
                        if not buffer_output_for_redaction:
                            yield f"data: {json.dumps(payload)}\n\n"
                else:
                    answer = result.answer if isinstance(result, RAGResponse) else str(result)
                    full_answer = answer
                    source_count = len(result.sources) if isinstance(result, RAGResponse) else 0
                    rerank_items = result.rerank_items if isinstance(result, RAGResponse) else 0
                    provider_usage = result.usage if isinstance(result, RAGResponse) else None
                    if not buffer_output_for_redaction:
                        yield f"data: {json.dumps({'token': answer, 'done': False})}\n\n"

                latency_ms = int((time.perf_counter() - start_time) * 1000)
                if buffer_output_for_redaction:
                    full_answer = redact_pii(full_answer)
                _, usage = TokenEngine.normalize_usage(
                    provider_usage or full_answer,
                    estimated_input_tokens=TokenEngine.estimate_text(question),
                    estimated_output_tokens=TokenEngine.estimate_text(full_answer),
                )
                execution = {
                    "model_call_count": 1,
                    "model_calls": [
                        {
                            "provider": body.provider,
                            "model": body.model,
                            "status": "completed",
                            "usage": usage.as_dict(),
                        }
                    ],
                    "total_tokens": usage.total_tokens,
                    "usage_source": usage.source,
                }
                actual_cost = await billing_service.calculate_cost(
                    provider=body.provider,
                    model=body.model,
                    operation="chat",
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    vector_searches=source_count,
                    reranks=rerank_items,
                    requests=1,
                )
                await billing_service.settle(
                    reservation.id,
                    actual_amount=actual_cost,
                    metadata={
                        "model": body.model,
                        "provider": body.provider,
                        "latency_ms": latency_ms,
                        "vector_searches": source_count,
                        "rerank_items": rerank_items,
                        "usage_source": usage.source,
                    },
                    transaction_type=TransactionType.RAG,
                )
                await billing_service.record_usage(
                    user_id=current_user.id, provider=body.provider, model=body.model, operation="chat", cost=actual_cost,
                    organization_id=current_user.organization_id, project_id=project_uuid, runtime_id=runtime_uuid,
                    request_id=request_id, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                    vector_searches=source_count, latency_ms=latency_ms,
                    metadata={
                        "rerank_items": rerank_items,
                        "usage_source": usage.source,
                        "routing_mode": "automatic" if dynamic_chat_routing else "configured",
                        "routing_reason": routing_reason,
                    },
                )
                db.add(
                    Event(
                        project_id=project_uuid,
                        organization_id=project.organization_id,
                        event_type="runtime.execution.completed",
                        data={
                            "request_id": request_id,
                            "runtime_id": body.runtime_id,
                            "model": body.model,
                            "provider": body.provider,
                            "routing_mode": "automatic" if dynamic_chat_routing else "configured",
                            "routing_reason": routing_reason,
                            "usage": usage.as_dict(),
                            "latency_ms": latency_ms,
                            "cost": float(actual_cost),
                            "context": getattr(result, "context", {}),
                            "source_count": source_count,
                            "rerank_items": rerank_items,
                            "execution": execution,
                        },
                    )
                )
                await db.commit()
                final_payload = {
                    "done": True,
                    "latency_ms": latency_ms,
                    "usage": usage.as_dict(),
                    "execution": execution,
                }
                if buffer_output_for_redaction:
                    final_payload["answer"] = full_answer
                yield f"data: {json.dumps(final_payload)}\n\n"
            except Exception:
                await billing_service.release(reservation.id, reason="chat_failed")
                raise

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    try:
        result = await pipeline.query(rag_query)
        if not isinstance(result, RAGResponse):
            raise HTTPException(status_code=500, detail="Invalid response type")
    except Exception:
        await billing_service.release(reservation.id, reason="chat_failed")
        raise

    answer_text = result.answer or ""
    output_violations = guardrail_service.validate_output(answer_text, body.json_schema)
    if output_violations:
        answer_text, _ = guardrail_service.enforce(answer_text, body.json_schema)
    if runtime and normalize_runtime_security_policy(runtime.security_policies)["pii_redaction"]:
        answer_text = redact_pii(answer_text)

    provider_usage = result.usage if isinstance(result.usage, dict) else None
    _, usage = TokenEngine.normalize_usage(
        provider_usage or {"total_tokens": result.tokens_used},
        estimated_input_tokens=TokenEngine.estimate_text(question),
        estimated_output_tokens=TokenEngine.estimate_text(answer_text),
    )
    execution = {
        "model_call_count": 1,
        "model_calls": [
            {
                "provider": body.provider,
                "model": body.model,
                "status": "completed",
                "usage": usage.as_dict(),
            }
        ],
        "total_tokens": usage.total_tokens,
        "usage_source": usage.source,
    }

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    actual_cost = await billing_service.calculate_cost(
        provider=body.provider,
        model=body.model,
        operation="chat",
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        vector_searches=len(result.sources),
        reranks=result.rerank_items,
        requests=1,
    )
    await billing_service.settle(
        reservation.id,
        actual_amount=actual_cost,
        metadata={
            "model": body.model,
            "provider": body.provider,
            "latency_ms": latency_ms,
            "vector_searches": len(result.sources),
            "rerank_items": result.rerank_items,
            "usage_source": usage.source,
        },
        transaction_type=TransactionType.RAG,
    )
    await billing_service.record_usage(
        user_id=current_user.id, provider=body.provider, model=body.model, operation="chat", cost=actual_cost,
        organization_id=current_user.organization_id, project_id=project_uuid, runtime_id=runtime_uuid,
        request_id=request_id, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
        vector_searches=len(result.sources), latency_ms=latency_ms,
        metadata={
            "rerank_items": result.rerank_items,
            "usage_source": usage.source,
            "context": result.context,
            "routing_mode": "automatic" if dynamic_chat_routing else "configured",
            "routing_reason": routing_reason,
        },
    )

    db.add(
        Event(
            project_id=project_uuid,
            organization_id=project.organization_id,
            event_type="runtime.execution.completed",
            data={
                "request_id": request_id,
                "runtime_id": body.runtime_id,
                "model": body.model,
                "provider": body.provider,
                "routing_mode": "automatic" if dynamic_chat_routing else "configured",
                "routing_reason": routing_reason,
                "usage": usage.as_dict(),
                "latency_ms": latency_ms,
                "cost": float(actual_cost),
                "context": result.context,
                "source_count": len(result.sources),
                "rerank_items": result.rerank_items,
                "execution": execution,
            },
        )
    )

    try:
        await uow.request_logs.create(
            project_id=project_uuid,
            request_id=f"chat-{int(start_time)}",
            method="POST",
            endpoint="/chat/completions",
            status=200,
            latency_ms=latency_ms,
            tokens=usage.total_tokens,
            provider=body.provider,
            model=body.model,
            cost=int(actual_cost),
            started_at=datetime.fromtimestamp(start_time, tz=timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
            user_id=current_user.id,
            ip="",
        )
        await uow.commit()
    except Exception:
        pass

    return ChatCompletionResponse(
        id="chatcmpl-rag",
        created=int(time.time()),
        model=body.model,
        choices=[
            ChatCompletionChoice(
                index=0,
                message={"role": "assistant", "content": answer_text},
                finish_reason="stop",
            )
        ],
        usage={
            "prompt_tokens": usage.input_tokens,
            "completion_tokens": usage.output_tokens,
            "total_tokens": usage.total_tokens,
            "source": usage.source,
            "routing_mode": "automatic" if dynamic_chat_routing else "configured",
            "routing_reason": routing_reason,
            "cost": float(actual_cost),
            "context": result.context,
            "execution": execution,
        },
        guardrail_violations=output_violations,
    )

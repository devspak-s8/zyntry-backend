from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_project_membership, require_runtime_access
from app.core.database import get_session
from app.models.users import User
from app.models.billing import TransactionType
from app.repositories import UnitOfWork
from app.schemas.rag import RAGQuery, RAGResponse
from app.services.billing import BillingService
from app.services.guardrails import GuardrailService
from app.services.rag import RAGPipeline
from app.services.runtime_capabilities import authorize_runtime_request, check_runtime_budget

router = APIRouter()
guardrail_service = GuardrailService()


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

    input_violations = guardrail_service.validate_input(question, body.json_schema)
    if input_violations:
        raise HTTPException(status_code=400, detail={"guardrail_violations": input_violations})

    rag_query = RAGQuery(
        question=question,
        project_id=project_id,
        user_id=str(current_user.id),
        runtime_id=body.runtime_id,
        top_k=body.top_k,
        filters=body.filters,
        stream=body.stream,
        conversation_id=body.conversation_id,
    )

    uow = UnitOfWork(db)
    pipeline = RAGPipeline(uow=uow)
    billing_service = BillingService(db)

    project_uuid = uuid.UUID(project_id)
    runtime_uuid = uuid.UUID(body.runtime_id) if body.runtime_id else None
    request_id = str(uuid.uuid4())
    estimated_cost = await billing_service.calculate_cost(
        provider=body.provider,
        model=body.model,
        operation="chat",
        input_tokens=len(question.split()),
        output_tokens=500,
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

        async def sse_generator() -> AsyncGenerator[str, None]:
            nonlocal full_answer
            source_count = 0
            rerank_items = 0
            try:
                result = await pipeline.query(rag_query)
                if hasattr(result, "__anext__"):
                    async for chunk in result:
                        payload = json.loads(chunk) if isinstance(chunk, str) else chunk
                        full_answer += payload.get("token", "")
                        source_count = max(source_count, len(payload.get("sources", [])))
                        rerank_items = max(rerank_items, int(payload.get("rerank_items", 0) or 0))
                        yield f"data: {json.dumps(payload)}\n\n"
                else:
                    answer = result.answer if isinstance(result, RAGResponse) else str(result)
                    full_answer = answer
                    source_count = len(result.sources) if isinstance(result, RAGResponse) else 0
                    rerank_items = result.rerank_items if isinstance(result, RAGResponse) else 0
                    yield f"data: {json.dumps({'token': answer, 'done': False})}\n\n"

                latency_ms = int((time.perf_counter() - start_time) * 1000)
                actual_cost = await billing_service.calculate_cost(
                    provider=body.provider,
                    model=body.model,
                    operation="chat",
                    input_tokens=len(question.split()),
                    output_tokens=len(full_answer.split()),
                    vector_searches=source_count,
                    reranks=rerank_items,
                    requests=1,
                )
                await billing_service.settle(reservation.id, actual_amount=actual_cost, metadata={"model": body.model, "provider": body.provider, "latency_ms": latency_ms, "vector_searches": source_count, "rerank_items": rerank_items}, transaction_type=TransactionType.RAG)
                await billing_service.record_usage(
                    user_id=current_user.id, provider=body.provider, model=body.model, operation="chat", cost=actual_cost,
                    organization_id=current_user.organization_id, project_id=project_uuid, runtime_id=runtime_uuid,
                    request_id=request_id, input_tokens=len(question.split()), output_tokens=len(full_answer.split()),
                    vector_searches=source_count, latency_ms=latency_ms,
                    metadata={"rerank_items": rerank_items},
                )
                yield f"data: {json.dumps({'done': True, 'latency_ms': latency_ms})}\n\n"
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

    latency_ms = int((time.perf_counter() - start_time) * 1000)
    actual_cost = await billing_service.calculate_cost(
        provider=body.provider,
        model=body.model,
        operation="chat",
        input_tokens=len(question.split()),
        output_tokens=len(answer_text.split()),
        vector_searches=len(result.sources),
        reranks=result.rerank_items,
        requests=1,
    )
    await billing_service.settle(reservation.id, actual_amount=actual_cost, metadata={"model": body.model, "provider": body.provider, "latency_ms": latency_ms, "vector_searches": len(result.sources), "rerank_items": result.rerank_items}, transaction_type=TransactionType.RAG)
    await billing_service.record_usage(
        user_id=current_user.id, provider=body.provider, model=body.model, operation="chat", cost=actual_cost,
        organization_id=current_user.organization_id, project_id=project_uuid, runtime_id=runtime_uuid,
        request_id=request_id, input_tokens=len(question.split()), output_tokens=len(answer_text.split()),
        vector_searches=len(result.sources), latency_ms=latency_ms,
        metadata={"rerank_items": result.rerank_items},
    )

    try:
        await uow.request_logs.create(
            project_id=project_uuid,
            request_id=f"chat-{int(start_time)}",
            method="POST",
            endpoint="/chat/completions",
            status=200,
            latency_ms=latency_ms,
            tokens=len(question.split()) + len(answer_text.split()),
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
            "prompt_tokens": len(question.split()),
            "completion_tokens": len(answer_text.split()),
            "total_tokens": len(question.split()) + len(answer_text.split()),
            "cost": float(actual_cost),
        },
        guardrail_violations=output_violations,
    )

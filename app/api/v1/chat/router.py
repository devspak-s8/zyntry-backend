from __future__ import annotations

import json
import time
import uuid
from decimal import Decimal
from typing import Annotated, AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.rag import RAGQuery, RAGResponse
from app.services.billing import BillingService
from app.services.guardrails import GuardrailService
from app.services.rag import RAGPipeline

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

    input_violations = guardrail_service.validate_input(question, body.json_schema)
    if input_violations:
        raise HTTPException(status_code=400, detail={"guardrail_violations": input_violations})

    rag_query = RAGQuery(
        question=question,
        project_id=project_id,
        runtime_id=body.runtime_id,
        top_k=body.top_k,
        filters=body.filters,
        stream=body.stream,
        conversation_id=body.conversation_id,
    )

    uow = UnitOfWork(db)
    pipeline = RAGPipeline(uow=uow)
    billing_service = BillingService(db)

    estimated_cost = await billing_service.calculate_cost(
        provider=body.provider,
        model=body.model,
        operation="chat",
        input_tokens=len(question.split()),
        output_tokens=500,
        requests=1,
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

    if body.stream:
        full_answer = ""

        async def sse_generator() -> AsyncGenerator[str, None]:
            nonlocal full_answer
            result = await pipeline.query(rag_query)
            if hasattr(result, "__anext__"):
                async for chunk in result:
                    full_answer += chunk.get("token", "") if isinstance(chunk, dict) else chunk
                    yield f"data: {chunk}\n\n"
            else:
                answer = result.answer if isinstance(result, RAGResponse) else str(result)
                full_answer = answer
                yield f"data: {json.dumps({'token': answer, 'done': False})}\n\n"

            latency_ms = int((time.perf_counter() - start_time) * 1000)
            actual_cost = await billing_service.calculate_cost(
                provider=body.provider,
                model=body.model,
                operation="chat",
                input_tokens=len(question.split()),
                output_tokens=len(full_answer.split()),
                requests=1,
            )
            try:
                await billing_service.deduct_credit(
                    user_id=current_user.id,
                    amount=actual_cost,
                    reason=f"Chat completion: {body.model}",
                    reference_id=f"chat-{int(start_time)}",
                    metadata={"model": body.model, "provider": body.provider, "latency_ms": latency_ms},
                )
                await billing_service.record_usage(
                    user_id=current_user.id,
                    provider=body.provider,
                    model=body.model,
                    operation="chat",
                    cost=actual_cost,
                    project_id=rag_query.project_id if rag_query.project_id else None,
                    runtime_id=rag_query.runtime_id if rag_query.runtime_id else None,
                    input_tokens=len(question.split()),
                    output_tokens=len(full_answer.split()),
                    latency_ms=latency_ms,
                )
            except Exception:
                pass

            yield f"data: {json.dumps({'done': True, 'latency_ms': latency_ms})}\n\n"

        return StreamingResponse(sse_generator(), media_type="text/event-stream")

    result = await pipeline.query(rag_query)
    if not isinstance(result, RAGResponse):
        raise HTTPException(status_code=500, detail="Invalid response type")

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
        requests=1,
    )

    try:
        await billing_service.deduct_credit(
            user_id=current_user.id,
            amount=actual_cost,
            reason=f"Chat completion: {body.model}",
            reference_id=f"chat-{int(start_time)}",
            metadata={"model": body.model, "provider": body.provider, "latency_ms": latency_ms},
        )
        await billing_service.record_usage(
            user_id=current_user.id,
            provider=body.provider,
            model=body.model,
            operation="chat",
            cost=actual_cost,
            project_id=rag_query.project_id if rag_query.project_id else None,
            runtime_id=rag_query.runtime_id if rag_query.runtime_id else None,
            input_tokens=len(question.split()),
            output_tokens=len(answer_text.split()),
            latency_ms=latency_ms,
        )
    except Exception:
        pass

    try:
        await uow.request_logs.create(
            project_id=uuid.UUID(rag_query.project_id) if rag_query.project_id else None,
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

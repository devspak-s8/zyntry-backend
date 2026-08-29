from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.dependencies_tenant import require_project_membership
from app.core.database import get_session
from app.models.users import User
from app.models.billing import TransactionType
from app.repositories import UnitOfWork
from app.services.billing import BillingService
from app.services.rag import RAGPipeline

router = APIRouter(prefix="/embeddings", tags=["embeddings"])


class EmbeddingRequest(BaseModel):
    input: str | list[str]
    model: str = "text-embedding-3-small"
    project_id: str | None = None
    provider: str = "openai"


class EmbeddingResponse(BaseModel):
    object: str = "list"
    data: list[dict]
    model: str
    usage: dict


@router.post("", response_model=EmbeddingResponse)
async def create_embeddings(
    body: EmbeddingRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> EmbeddingResponse:
    project_uuid: uuid.UUID | None = None
    if body.project_id:
        try:
            project_uuid = uuid.UUID(body.project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid project id") from exc
        await require_project_membership(body.project_id, current_user, db)

    texts = body.input if isinstance(body.input, list) else [body.input]
    token_count = sum(len(t.split()) for t in texts)

    billing_service = BillingService(db)
    estimated_cost = await billing_service.calculate_cost(
        provider=body.provider,
        model=body.model,
        operation="embeddings",
        embedding_tokens=token_count,
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

    dummy_response = EmbeddingResponse(
        object="list",
        data=[{"object": "embedding", "embedding": [0.0] * 1536, "index": i} for i in range(len(texts))],
        model=body.model,
        usage={"prompt_tokens": token_count, "total_tokens": token_count},
    )

    request_id = str(uuid.uuid4())
    reservation = await billing_service.reserve(
        user_id=current_user.id,
        amount=estimated_cost,
        request_id=request_id,
        idempotency_key=f"embedding:{request_id}",
        organization_id=current_user.organization_id,
        project_id=project_uuid,
        resource_type="embedding",
        metadata={"model": body.model, "provider": body.provider, "texts_count": len(texts)},
    )
    try:
        await billing_service.settle(
            reservation.id,
            actual_amount=estimated_cost,
            metadata={"model": body.model, "provider": body.provider, "texts_count": len(texts)},
            transaction_type=TransactionType.EMBEDDING,
        )
        await billing_service.record_usage(
            user_id=current_user.id,
            provider=body.provider,
            model=body.model,
            operation="embeddings",
            cost=estimated_cost,
            organization_id=current_user.organization_id,
            project_id=project_uuid,
            request_id=request_id,
            input_tokens=token_count,
            embedding_tokens=token_count,
            requests=1,
        )
    except Exception:
        await billing_service.release(reservation.id, reason="embedding_failed")
        raise

    return dummy_response

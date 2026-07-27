from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.database import get_session
from app.models.billing import WalletStatus
from app.models.users import User
from app.repositories import UnitOfWork
from app.schemas.billing import EstimateCostRequest, InsufficientCreditsError
from app.services.billing import BillingService, InsufficientCredits


async def _get_billing_service(db: AsyncSession = Depends(get_session)) -> BillingService:
    return BillingService(db)


async def require_sufficient_balance(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    provider: str = "openai",
    model: str = "gpt-4o",
    operation: str = "chat",
    input_tokens: int = 0,
    output_tokens: int = 0,
    embedding_tokens: int = 0,
    vector_searches: int = 0,
    storage_bytes: int = 0,
    requests: int = 1,
) -> BillingService:
    service = BillingService(db)
    wallet = await service.get_wallet(current_user.id)

    if wallet.status != WalletStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Insufficient Credits",
                "required": Decimal("0"),
                "balance": wallet.balance,
            },
        )

    estimated_cost = await service.calculate_cost(
        provider=provider,
        model=model,
        operation=operation,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        embedding_tokens=embedding_tokens,
        vector_searches=vector_searches,
        storage_bytes=storage_bytes,
        requests=requests,
    )

    budget_ok = await service.check_budget(current_user.id, estimated_cost)
    if not budget_ok:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "Budget limit reached",
                "required": estimated_cost,
                "balance": wallet.balance,
            },
        )

    if wallet.balance < estimated_cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=InsufficientCreditsError(required=estimated_cost, balance=wallet.balance).model_dump(),
        )

    return service

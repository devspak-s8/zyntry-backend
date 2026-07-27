from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Annotated

import stripe
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.core.config import settings
from app.core.database import get_session
from app.models.users import User
from app.repositories import UnitOfWork
from app.repositories.processed_webhook_events import ProcessedWebhookEventRepository
from app.schemas.billing import (
    AddCreditsRequest,
    BudgetCreate,
    BudgetRead,
    BudgetUpdate,
    CheckoutSessionRequest,
    CheckoutSessionResponse,
    EstimateCostRequest,
    EstimateCostResponse,
    InsufficientCreditsError,
    PricingRuleRead,
    RefundRequest,
    UsageLogRead,
    UsageSummary,
    WalletRead,
    WalletTransactionRead,
)
from app.services.billing import BillingService, InsufficientCredits

router = APIRouter(prefix="/wallet", tags=["wallet"])


def _require_stripe() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe is not configured")


@router.get("", response_model=WalletRead)
async def get_wallet(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> WalletRead:
    service = BillingService(db)
    return await service.get_wallet_read(current_user.id)


@router.get("/transactions", response_model=list[WalletTransactionRead])
async def list_transactions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[WalletTransactionRead]:
    service = BillingService(db)
    return await service.get_transactions(current_user.id, limit=limit, offset=offset)


@router.post("/add-credits", response_model=CheckoutSessionResponse)
async def create_checkout_session(
    body: CheckoutSessionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> CheckoutSessionResponse:
    _require_stripe()
    stripe.api_key = settings.STRIPE_SECRET_KEY

    service = BillingService(db)
    wallet = await service.get_wallet(current_user.id)

    success_url = body.success_url or f"{settings.APP_URL}/billing?success=true"
    cancel_url = body.cancel_url or f"{settings.APP_URL}/billing?canceled=true"

    try:
        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price_data": {
                        "currency": body.currency,
                        "product_data": {
                            "name": "Zyntra Credits",
                        },
                        "unit_amount": int(body.amount * 100),
                    },
                    "quantity": 1,
                }
            ],
            mode="payment",
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "user_id": str(current_user.id),
                "wallet_id": str(wallet.id),
                "amount": str(body.amount),
            },
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return CheckoutSessionResponse(session_id=checkout_session.id, url=checkout_session.url or "")


class WebhookBody(BaseModel):
    id: str


@router.post("/stripe-webhook", response_model=dict)
async def stripe_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Stripe webhook secret not configured")

    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid webhook signature: {exc}") from exc

    event_id = event.get("id", "")
    event_type = event.get("type", "")

    async with db:
        processed_repo = ProcessedWebhookEventRepository(db)
        existing = await processed_repo.get_by_event_id(event_id)
        if existing:
            return {"received": True, "deduplicated": True}

        if event_type == "checkout.session.completed":
            session = event["data"]["object"]
            metadata = session.get("metadata", {})
            user_id = metadata.get("user_id")
            amount = Decimal(metadata.get("amount", "0"))
            wallet_id = metadata.get("wallet_id")

            if not user_id or not wallet_id:
                raise HTTPException(status_code=400, detail="Missing metadata in checkout session")

            service = BillingService(db)
            try:
                await service.add_credit(
                    user_id=uuid.UUID(user_id),
                    amount=amount,
                    reason="Stripe payment",
                    reference_id=event_id,
                    metadata={"stripe_session_id": session["id"], "payment_status": session.get("payment_status")},
                )
            except Exception:
                raise

        processed_repo.create(
            event_id=event_id,
            source="stripe",
            event_type=event_type,
            status="processed",
            payload=dict(event),
            received_at=datetime.now(timezone.utc),
        )
        await db.commit()
        return {"received": True}


@router.post("/refund", response_model=WalletTransactionRead)
async def refund_transaction(
    body: RefundRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> WalletTransactionRead:
    service = BillingService(db)
    txn = await service.refund_transaction(current_user.id, body)
    return WalletTransactionRead(
        id=txn.id,
        wallet_id=txn.wallet_id,
        type=txn.type,
        amount=txn.amount,
        balance_before=txn.balance_before,
        balance_after=txn.balance_after,
        reason=txn.reason,
        reference_id=txn.reference_id,
        metadata=txn.metadata_,
        created_at=txn.created_at,
    )


@router.get("/usage", response_model=UsageSummary)
async def get_usage(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> UsageSummary:
    service = BillingService(db)
    summary = await service.get_usage_summary(current_user.id)
    return UsageSummary(**summary)


@router.get("/usage/logs", response_model=list[UsageLogRead])
async def list_usage_logs(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[UsageLogRead]:
    uow = UnitOfWork(db)
    result = await uow.session.execute(
        select(UsageLog)
        .where(UsageLog.user_id == current_user.id)
        .order_by(UsageLog.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    logs = result.scalars().all()
    return [
        UsageLogRead(
            id=log.id,
            user_id=log.user_id,
            project_id=log.project_id,
            runtime_id=log.runtime_id,
            provider=log.provider,
            model=log.model,
            operation=log.operation,
            input_tokens=log.input_tokens,
            output_tokens=log.output_tokens,
            embedding_tokens=log.embedding_tokens,
            vector_searches=log.vector_searches,
            storage_bytes=log.storage_bytes,
            requests=log.requests,
            latency_ms=log.latency_ms,
            cost=log.cost,
            metadata=log.metadata_,
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.get("/pricing", response_model=list[PricingRuleRead])
async def list_pricing(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    provider: str | None = Query(default=None),
    operation: str | None = Query(default=None),
) -> list[PricingRuleRead]:
    uow = UnitOfWork(db)
    rules = await uow.pricing_rules.list_active(provider=provider, operation=operation)
    return [
        PricingRuleRead(
            id=r.id,
            provider=r.provider,
            operation=r.operation,
            model=r.model,
            unit=r.unit,
            price_per_unit=r.price_per_unit,
            currency=r.currency,
            active=r.active,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rules
    ]


@router.post("/estimate", response_model=EstimateCostResponse)
async def estimate_cost(
    body: EstimateCostRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> EstimateCostResponse:
    service = BillingService(db)
    return await service.estimate_request_cost(body)


@router.get("/budget", response_model=BudgetRead | None)
async def get_budget(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> BudgetRead | None:
    service = BillingService(db)
    budget = await service.get_budget(current_user.id)
    if budget is None:
        return None
    return BudgetRead(
        id=budget.id,
        user_id=budget.user_id,
        monthly_limit=budget.monthly_limit,
        current_spend=budget.current_spend,
        warning_80_sent=budget.warning_80_sent,
        warning_90_sent=budget.warning_90_sent,
        limit_reached=budget.limit_reached,
        auto_top_up_enabled=budget.auto_top_up_enabled,
        auto_top_up_threshold=budget.auto_top_up_threshold,
        auto_top_up_amount=budget.auto_top_up_amount,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


@router.put("/budget", response_model=BudgetRead)
async def update_budget(
    body: BudgetUpdate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> BudgetRead:
    service = BillingService(db)
    if body.monthly_limit is not None and body.monthly_limit > Decimal("0"):
        budget = await service.create_or_update_budget(current_user.id, BudgetCreate(monthly_limit=body.monthly_limit))
    else:
        budget = await service.update_budget(current_user.id, body)
        if budget is None:
            budget = await service.create_or_update_budget(current_user.id, BudgetCreate(monthly_limit=Decimal("0")))

    return BudgetRead(
        id=budget.id,
        user_id=budget.user_id,
        monthly_limit=budget.monthly_limit,
        current_spend=budget.current_spend,
        warning_80_sent=budget.warning_80_sent,
        warning_90_sent=budget.warning_90_sent,
        limit_reached=budget.limit_reached,
        auto_top_up_enabled=budget.auto_top_up_enabled,
        auto_top_up_threshold=budget.auto_top_up_threshold,
        auto_top_up_amount=budget.auto_top_up_amount,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )


@router.post("/budget", response_model=BudgetRead, status_code=status.HTTP_201_CREATED)
async def create_budget(
    body: BudgetCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> BudgetRead:
    service = BillingService(db)
    budget = await service.create_or_update_budget(current_user.id, body)
    return BudgetRead(
        id=budget.id,
        user_id=budget.user_id,
        monthly_limit=budget.monthly_limit,
        current_spend=budget.current_spend,
        warning_80_sent=budget.warning_80_sent,
        warning_90_sent=budget.warning_90_sent,
        limit_reached=budget.limit_reached,
        auto_top_up_enabled=budget.auto_top_up_enabled,
        auto_top_up_threshold=budget.auto_top_up_threshold,
        auto_top_up_amount=budget.auto_top_up_amount,
        created_at=budget.created_at,
        updated_at=budget.updated_at,
    )

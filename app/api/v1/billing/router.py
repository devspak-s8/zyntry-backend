from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import get_current_user
from app.api.v1.features.dependencies import require_feature
from app.core.config import settings
from app.core.database import get_session
from app.models.apikeys import ApiKey
from app.models.billing import BillingLedger, SpendingLimit, UsageLog
from app.models.projects import Project
from app.models.runtimes import Runtime
from app.models.users import User
from app.repositories import UnitOfWork
from app.repositories.processed_webhook_events import ProcessedWebhookEventRepository
from app.schemas.billing import (
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
    BillingLedgerRead,
    SpendingLimitCreate,
    SpendingLimitRead,
)
from app.services.bachs import BachsService, BachsError
from app.services.billing import BillingService, InsufficientCredits
from app.services.metered_billing import MeteredBillingService
from app.core.ws_events import emit_checkout_completed, emit_wallet_updated

router = APIRouter(prefix="/wallet", tags=["wallet"])
BILLING_GUARD = [Depends(require_feature("billing"))]
CREDIT_PURCHASE_GUARD = [
    Depends(require_feature("billing")),
    Depends(require_feature("credit_purchases")),
]


def _require_bachs() -> BachsService:
    if not settings.BACHS_API_KEY:
        raise HTTPException(status_code=500, detail="Bachs is not configured")
    return BachsService()


@router.get("", response_model=WalletRead, dependencies=BILLING_GUARD)
async def get_wallet(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> WalletRead:
    service = BillingService(db)
    return await service.get_wallet_read(current_user.id)


@router.get("/transactions", response_model=list[WalletTransactionRead], dependencies=BILLING_GUARD)
async def list_transactions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[WalletTransactionRead]:
    service = BillingService(db)
    return await service.get_transactions(current_user.id, limit=limit, offset=offset)


@router.get("/ledger", response_model=list[BillingLedgerRead], dependencies=BILLING_GUARD)
async def list_billing_ledger(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[BillingLedgerRead]:
    result = await db.execute(
        select(BillingLedger)
        .where(BillingLedger.user_id == current_user.id)
        .order_by(BillingLedger.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return [BillingLedgerRead(
        id=row.id, transaction_type=row.transaction_type, user_id=row.user_id,
        organization_id=row.organization_id, project_id=row.project_id,
        runtime_id=row.runtime_id, api_key_id=row.api_key_id,
        request_id=row.request_id, resource_type=row.resource_type,
        resource_id=row.resource_id, amount=row.amount, currency=row.currency,
        provider_cost=row.provider_cost, platform_markup=row.platform_markup,
        status=row.status, metadata=row.metadata_, created_at=row.created_at,
    ) for row in result.scalars().all()]


@router.get("/limits", response_model=list[SpendingLimitRead], dependencies=BILLING_GUARD)
async def list_spending_limits(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> list[SpendingLimitRead]:
    result = await db.execute(select(SpendingLimit).where(SpendingLimit.scope_type == "user", SpendingLimit.scope_id == current_user.id))
    return [SpendingLimitRead.model_validate(row) for row in result.scalars().all()]


@router.post("/limits", response_model=SpendingLimitRead, status_code=status.HTTP_201_CREATED, dependencies=BILLING_GUARD)
async def create_spending_limit(
    body: SpendingLimitCreate,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> SpendingLimitRead:
    if body.scope_type == "user" and body.scope_id != current_user.id:
        raise HTTPException(status_code=403, detail="Cannot configure another user's limit")
    if body.scope_type == "organization" and body.scope_id != current_user.organization_id:
        raise HTTPException(status_code=403, detail="Organization is outside your account")
    if body.scope_type == "project":
        project = await db.scalar(select(Project).where(Project.id == body.scope_id, Project.organization_id == current_user.organization_id))
        if project is None:
            raise HTTPException(status_code=403, detail="Project is outside your organization")
    if body.scope_type == "runtime":
        runtime = await db.scalar(select(Runtime).where(Runtime.id == body.scope_id, Runtime.organization_id == current_user.organization_id))
        if runtime is None:
            raise HTTPException(status_code=403, detail="Runtime is outside your organization")
    if body.scope_type == "api_key":
        api_key = await db.scalar(select(ApiKey).where(ApiKey.id == body.scope_id, ApiKey.organization_id == current_user.organization_id))
        if api_key is None:
            raise HTTPException(status_code=403, detail="API key is outside your organization")
    row = await db.scalar(select(SpendingLimit).where(SpendingLimit.scope_type == body.scope_type, SpendingLimit.scope_id == body.scope_id, SpendingLimit.period == body.period))
    if row is None:
        row = SpendingLimit(**body.model_dump())
        db.add(row)
    else:
        row.amount = body.amount
        row.active = True
    await db.commit()
    await db.refresh(row)
    return SpendingLimitRead.model_validate(row)


@router.get("/reconciliation", dependencies=BILLING_GUARD)
async def reconcile_wallet(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    return await MeteredBillingService(db).reconcile_wallet(current_user.id)


@router.get("/analytics", dependencies=BILLING_GUARD)
async def billing_analytics(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
    days: int = Query(default=30, ge=1, le=365),
) -> dict:
    """Return customer-visible spend breakdowns for billing dashboards."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    base = [BillingLedger.user_id == current_user.id, BillingLedger.status == "settled", BillingLedger.created_at >= since]

    async def grouped(label: str, expression):
        result = await db.execute(
            select(expression.label(label), func.sum(BillingLedger.amount).label("amount"), func.count().label("events"))
            .where(*base)
            .group_by(expression)
            .order_by(func.sum(BillingLedger.amount).desc())
            .limit(100)
        )
        return [
            {label: row[0], "amount": float(row[1] or 0), "events": int(row[2] or 0)}
            for row in result.all()
        ]

    daily = await db.execute(
        select(func.date(BillingLedger.created_at).label("day"), func.sum(BillingLedger.amount).label("amount"), func.count().label("events"))
        .where(*base)
        .group_by(func.date(BillingLedger.created_at))
        .order_by(func.date(BillingLedger.created_at))
    )
    return {
        "period_days": days,
        "by_provider": await grouped("provider", BillingLedger.metadata_["provider"].as_string()),
        "by_model": await grouped("model", BillingLedger.metadata_["model"].as_string()),
        "by_operation": await grouped("resource_type", BillingLedger.resource_type),
        "by_project": await grouped("project_id", BillingLedger.project_id),
        "by_runtime": await grouped("runtime_id", BillingLedger.runtime_id),
        "daily": [{"day": str(row.day), "amount": float(row.amount or 0), "events": int(row.events or 0)} for row in daily.all()],
    }


@router.post("/add-credits", response_model=CheckoutSessionResponse, dependencies=CREDIT_PURCHASE_GUARD)
async def create_checkout_session(
    body: CheckoutSessionRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> CheckoutSessionResponse:
    bachs = _require_bachs()
    service = BillingService(db)
    wallet = await service.get_wallet(current_user.id)

    success_url = body.success_url or f"{settings.APP_URL}/billing?success=true"
    cancel_url = body.cancel_url or f"{settings.APP_URL}/billing?canceled=true"

    amount_str = str(Decimal(body.amount).quantize(Decimal("0.01")))
    reference = f"wallet-{current_user.id}-{int(datetime.now(timezone.utc).timestamp())}"

    customer = None
    existing_customers = await bachs.list_customers(search=current_user.email, limit=1)
    items = existing_customers.get("items") or []
    if items:
        c = items[0]
        customer = BachsCustomer(
            id=c.get("id"),
            email=c.get("email") or current_user.email,
            name=c.get("name") or current_user.name or current_user.email,
        )
    else:
        customer = await bachs.create_customer(email=current_user.email, name=current_user.name or current_user.email)

    checkout_customer = customer if customer else None

    try:
        checkout = await bachs.create_checkout_session(
            amount=amount_str,
            currency=body.currency.upper(),
            success_url=success_url,
            cancel_url=cancel_url,
            customer=checkout_customer,
            metadata={
                "user_id": str(current_user.id),
                "wallet_id": str(wallet.id),
                "amount": amount_str,
                "zyntry_wallet_topup": "true",
            },
            reference=reference,
            allowed_payment_method_types=["card"],
        )
    except BachsError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    await emit_checkout_completed(str(current_user.id), checkout.checkout_id, checkout.status)

    return CheckoutSessionResponse(session_id=checkout.checkout_id, url=checkout.checkout_url, status=checkout.status)


@router.post("/bachs-webhook", response_model=dict)
async def bachs_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    if not settings.BACHS_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Bachs webhook secret not configured")

    payload = await request.body()
    timestamp_header = request.headers.get("X-Bachs-Timestamp", "")
    signature_header = request.headers.get("X-Bachs-Signature", "")

    from app.services.bachs import verify_bachs_signature
    if not verify_bachs_signature(payload, settings.BACHS_WEBHOOK_SECRET, timestamp_header, signature_header):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    try:
        event = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    event_id = event.get("id", "")
    event_type = event.get("type", "")

    async with db:
        processed_repo = ProcessedWebhookEventRepository(db)
        existing = await processed_repo.get_by_event_id(event_id)
        if existing:
            return {"received": True, "deduplicated": True}

        if event_type == "collection.succeeded":
            data = event.get("data", {})
            metadata = data.get("metadata") or {}
            user_id = metadata.get("user_id")
            amount_raw = metadata.get("amount")

            if not user_id or not amount_raw:
                raise HTTPException(status_code=400, detail="Missing metadata in Bachs event")

            try:
                amount = Decimal(str(amount_raw))
            except Exception:
                amount = Decimal("0")

            service = BillingService(db)
            try:
                await service.add_credit(
                    user_id=uuid.UUID(user_id),
                    amount=amount,
                    reason="Wallet top-up",
                    reference_id=event_id,
                    metadata={
                        "provider": "bachs",
                        "checkout_id": data.get("checkout_id"),
                        "charge_id": data.get("charge_id"),
                        "payment_method": data.get("payment_method"),
                        "currency": data.get("currency"),
                    },
                )
                wallet = await service.get_wallet(uuid.UUID(user_id))
                await emit_wallet_updated(user_id, str(wallet.id), str(wallet.balance), wallet.currency)
            except Exception:
                raise

        processed_repo.create(
            event_id=event_id,
            source="bachs",
            event_type=event_type,
            status="processed",
            payload=event,
            received_at=datetime.now(timezone.utc),
        )
        await db.commit()
        return {"received": True}


@router.post("/refund", response_model=WalletTransactionRead, dependencies=BILLING_GUARD)
async def refund_transaction(
    body: RefundRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> WalletTransactionRead:
    service = BillingService(db)
    txn = await service.refund_transaction(current_user.id, body)
    wallet = await service.get_wallet(current_user.id)
    await emit_wallet_updated(str(current_user.id), str(wallet.id), str(wallet.balance), wallet.currency)
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


@router.get("/usage", response_model=UsageSummary, dependencies=BILLING_GUARD)
async def get_usage(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> UsageSummary:
    service = BillingService(db)
    summary = await service.get_usage_summary(current_user.id)
    return UsageSummary(**summary)


@router.get("/usage/logs", response_model=list[UsageLogRead], dependencies=BILLING_GUARD)
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
            organization_id=log.organization_id,
            project_id=log.project_id,
            runtime_id=log.runtime_id,
            api_key_id=log.api_key_id,
            request_id=log.request_id,
            provider=log.provider,
            model=log.model,
            operation=log.operation,
            input_tokens=log.input_tokens,
            output_tokens=log.output_tokens,
            cached_tokens=log.cached_tokens,
            embedding_tokens=log.embedding_tokens,
            vector_searches=log.vector_searches,
            storage_bytes=log.storage_bytes,
            requests=log.requests,
            latency_ms=log.latency_ms,
            cost=log.cost,
            provider_cost=log.provider_cost,
            platform_markup=log.platform_markup,
            metadata=log.metadata_,
            created_at=log.created_at,
        )
        for log in logs
    ]


@router.get("/pricing", response_model=list[PricingRuleRead], dependencies=BILLING_GUARD)
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
            cached_price_per_unit=r.cached_price_per_unit,
            markup=r.markup,
            effective_from=r.effective_from,
            effective_until=r.effective_until,
            version=r.version,
            created_at=r.created_at,
            updated_at=r.updated_at,
        )
        for r in rules
    ]


@router.post("/estimate", response_model=EstimateCostResponse, dependencies=BILLING_GUARD)
async def estimate_cost(
    body: EstimateCostRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_session)],
) -> EstimateCostResponse:
    service = BillingService(db)
    return await service.estimate_request_cost(body)


@router.get("/budget", response_model=BudgetRead | None, dependencies=BILLING_GUARD)
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


@router.put("/budget", response_model=BudgetRead, dependencies=BILLING_GUARD)
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


@router.post("/budget", response_model=BudgetRead, status_code=status.HTTP_201_CREATED, dependencies=BILLING_GUARD)
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

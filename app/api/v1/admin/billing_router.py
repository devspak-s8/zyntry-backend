from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    BillingOverviewRead,
    ProviderFundingRead,
    ProviderFundingReconcile,
    ProviderFundingUpdate,
    WalletAdjustRequest,
    WalletCreditRequest,
    WalletDebitRequest,
    WalletDetailRead,
    WalletFreezeRequest,
    WalletRefundRequest,
    WalletTransactionRead,
)
from app.admin.services.billing_admin import BillingAdminService
from app.core.database import get_session
from app.services.provider_funding import ProviderFundingService

router = APIRouter(prefix="/admin", tags=["admin-billing"])


@router.get("/billing/provider-funding", response_model=list[ProviderFundingRead])
async def admin_list_provider_funding(
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[ProviderFundingRead]:
    accounts = await ProviderFundingService(db).list_accounts()
    return [ProviderFundingRead(**ProviderFundingService.serialize(account)) for account in accounts]


@router.put("/billing/provider-funding/{provider}", response_model=ProviderFundingRead)
async def admin_configure_provider_funding(
    provider: str,
    body: ProviderFundingUpdate,
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> ProviderFundingRead:
    try:
        account = await ProviderFundingService(db).configure(
            provider,
            account_label=body.account_label,
            currency=body.currency,
            funding_mode=body.funding_mode,
            monitor_enabled=body.monitor_enabled,
            auto_top_up_enabled=body.auto_top_up_enabled,
            current_balance=body.current_balance,
            estimated_balance=body.estimated_balance,
            minimum_balance=body.minimum_balance,
            target_balance=body.target_balance,
            max_top_up=body.max_top_up,
            daily_top_up_limit=body.daily_top_up_limit,
            payment_method_ref=body.payment_method_ref,
            external_account_ref=body.external_account_ref,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ProviderFundingRead(**ProviderFundingService.serialize(account))


@router.post("/billing/provider-funding/{provider}/check", response_model=ProviderFundingRead)
async def admin_check_provider_funding(
    provider: str,
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_READ)),
    db: AsyncSession = Depends(get_session),
) -> ProviderFundingRead:
    service = ProviderFundingService(db)
    account = await service.get_account(provider)
    if account is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider funding account not found")
    return ProviderFundingRead(**await service.check_account(account))


@router.post("/billing/provider-funding/{provider}/reconcile", response_model=ProviderFundingRead)
async def admin_reconcile_provider_funding(
    provider: str,
    body: ProviderFundingReconcile,
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> ProviderFundingRead:
    try:
        account = await ProviderFundingService(db).reconcile(
            provider,
            body.balance,
            external_id=body.external_id,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return ProviderFundingRead(**ProviderFundingService.serialize(account))


@router.get("/billing/overview", response_model=BillingOverviewRead)
async def admin_billing_overview(
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_READ)),
    db: AsyncSession = Depends(get_session),
) -> BillingOverviewRead:
    service = BillingAdminService(db)
    overview = await service.get_billing_overview()
    return BillingOverviewRead(**overview)


@router.get("/billing/wallets", response_model=list[WalletDetailRead])
async def admin_list_wallets(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: str | None = Query(default=None),
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[WalletDetailRead]:
    service = BillingAdminService(db)
    wallets = await service.list_wallets(limit=limit, offset=offset, status=status)
    return [WalletDetailRead(**w) for w in wallets]


@router.get("/billing/wallets/{user_id}", response_model=WalletDetailRead)
async def admin_get_wallet(
    user_id: str,
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_READ)),
    db: AsyncSession = Depends(get_session),
) -> WalletDetailRead:
    service = BillingAdminService(db)
    wallet = await service.get_wallet_details(user_id)
    if wallet is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")
    return WalletDetailRead(**wallet)


@router.post("/billing/wallets/{user_id}/credit", response_model=WalletTransactionRead)
async def admin_credit_wallet(
    user_id: str,
    body: WalletCreditRequest,
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> WalletTransactionRead:
    service = BillingAdminService(db)
    result = await service.credit_wallet(user_id, body.amount, body.reason)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return WalletTransactionRead(**result)


@router.post("/billing/wallets/{user_id}/debit", response_model=WalletTransactionRead)
async def admin_debit_wallet(
    user_id: str,
    body: WalletDebitRequest,
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> WalletTransactionRead:
    service = BillingAdminService(db)
    result = await service.debit_wallet(user_id, body.amount, body.reason)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return WalletTransactionRead(**result)


@router.post("/billing/wallets/{user_id}/adjust", response_model=WalletTransactionRead)
async def admin_adjust_balance(
    user_id: str,
    body: WalletAdjustRequest,
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> WalletTransactionRead:
    service = BillingAdminService(db)
    result = await service.adjust_balance(user_id, body.new_balance, body.reason)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result["error"])
    return WalletTransactionRead(**result)


@router.post("/billing/wallets/{user_id}/refund", response_model=WalletTransactionRead)
async def admin_refund_transaction(
    user_id: str,
    body: WalletRefundRequest,
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> WalletTransactionRead:
    service = BillingAdminService(db)
    result = await service.refund_transaction(user_id, body.transaction_id, body.reason)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=result["error"])
    return WalletTransactionRead(**result)


@router.post("/billing/wallets/{user_id}/freeze")
async def admin_freeze_wallet(
    user_id: str,
    body: WalletFreezeRequest | None = None,
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_WRITE)),
    db: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    service = BillingAdminService(db)
    result = await service.freeze_wallet(user_id, body.reason if body else None)
    return result


@router.get("/billing/transactions", response_model=list[WalletTransactionRead])
async def admin_list_transactions(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx: AdminContext = Depends(require_permission(Permission.BILLING_READ)),
    db: AsyncSession = Depends(get_session),
) -> list[WalletTransactionRead]:
    service = BillingAdminService(db)
    transactions = await service.list_transactions(limit=limit, offset=offset)
    return [WalletTransactionRead(**t) for t in transactions]

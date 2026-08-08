from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import Permission
from app.admin.dependencies import AdminContext, require_permission
from app.admin.schemas import (
    BillingOverviewRead,
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

router = APIRouter(prefix="/admin", tags=["admin-billing"])


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
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.models import WalletFreeze
from app.admin.repositories import WalletFreezeRepository
from app.models.billing import Wallet, WalletTransaction
from app.schemas.billing import RefundRequest
from app.services.billing import BillingService, InsufficientCredits
from app.models.organizations import Organization
from app.models.users import User


class BillingAdminService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._freeze_repo = WalletFreezeRepository(db)

    async def get_billing_overview(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        wallet_balance = await self.db.scalar(select(func.coalesce(func.sum(Wallet.balance), 0)).where(Wallet.status == "active"))
        credits_purchased = Decimal("0")
        credits_used = Decimal("0")
        provider_cost = Decimal("0")
        refunds = Decimal("0")
        platform_revenue = Decimal("0")
        profit = Decimal("0")
        profit_margin = Decimal("0")

        top_customers = []
        monthly_revenue = Decimal("0")

        return {
            "wallet_balance": float(wallet_balance or 0),
            "credits_purchased": float(credits_purchased),
            "credits_used": float(credits_used),
            "provider_cost": float(provider_cost),
            "refunds": float(refunds),
            "platform_revenue": float(platform_revenue),
            "profit": float(profit),
            "profit_margin": float(profit_margin),
            "top_customers": top_customers,
            "monthly_revenue": float(monthly_revenue),
        }

    async def get_wallet_details(self, user_id: str) -> dict[str, Any] | None:
        uid = user_id
        result = await self.db.execute(select(Wallet).where(Wallet.user_id == uid))
        wallet = result.scalar_one_or_none()
        if wallet is None:
            return None

        user_result = await self.db.execute(select(User).where(User.id == uid))
        user_row = user_result.scalar_one_or_none()

        return {
            "id": str(wallet.id) if wallet.id else None,
            "user_id": uid,
            "user_name": user_row.name if user_row else None,
            "org_name": None,
            "balance": float(wallet.balance),
            "reserved_balance": float(wallet.reserved_balance),
            "total_spent": float(wallet.total_spent),
            "total_topups": float(wallet.total_topups),
            "currency": "usd",
            "status": wallet.status,
            "created_at": wallet.created_at.isoformat() if wallet.created_at else "",
            "updated_at": wallet.updated_at.isoformat() if wallet.updated_at else "",
        }

    async def credit_wallet(self, user_id: str, amount: float, reason: str | None = None) -> dict[str, Any]:
        service = BillingService(self.db)
        wallet = await service.get_wallet(uuid.UUID(user_id))
        balance_before = wallet.balance
        transaction = await service.add_credit(uuid.UUID(user_id), Decimal(str(amount)), reason or "Admin credit", reference_id=f"admin-credit:{user_id}:{datetime.now(UTC).timestamp()}")
        wallet = await service.get_wallet(uuid.UUID(user_id))

        return {
            "transaction_id": str(transaction.id) if transaction.id else "",
            "type": "credit",
            "amount": amount,
            "balance_before": float(balance_before),
            "balance_after": float(wallet.balance),
            "reason": reason,
        }

    async def debit_wallet(self, user_id: str, amount: float, reason: str | None = None) -> dict[str, Any]:
        service = BillingService(self.db)
        uid = uuid.UUID(user_id)
        wallet = await service.get_wallet(uid)
        balance_before = wallet.balance
        try:
            transaction = await service.deduct_credit(uid, Decimal(str(amount)), reason or "Admin debit", reference_id=f"admin-debit:{user_id}:{datetime.now(UTC).timestamp()}")
        except InsufficientCredits as exc:
            return {"error": "Insufficient balance", "required": float(exc.required), "balance": float(exc.balance)}
        wallet = await service.get_wallet(uid)

        return {
            "transaction_id": str(transaction.id) if transaction.id else "",
            "type": "debit",
            "amount": amount,
            "balance_before": float(balance_before),
            "balance_after": float(wallet.balance),
            "reason": reason,
        }

    async def refund_transaction(self, user_id: str, transaction_id: str, reason: str | None = None) -> dict[str, Any]:
        uid = uuid.UUID(user_id)
        service = BillingService(self.db)
        wallet = await service.get_wallet(uid)
        balance_before = wallet.balance
        try:
            refund_txn = await service.refund_transaction(uid, RefundRequest(transaction_id=uuid.UUID(transaction_id), reason=reason or "Admin refund"))
        except ValueError as exc:
            return {"error": str(exc)}
        wallet = await service.get_wallet(uid)

        return {
            "transaction_id": str(refund_txn.id) if refund_txn.id else "",
            "type": "refund",
            "amount": original.amount,
            "balance_before": float(balance_before),
            "balance_after": float(wallet.balance),
            "reason": reason,
        }

    async def adjust_balance(self, user_id: str, new_balance: float, reason: str | None = None) -> dict[str, Any]:
        uid = uuid.UUID(user_id)
        service = BillingService(self.db)
        wallet = await service.get_wallet(uid)
        balance_before = wallet.balance
        amount = Decimal(str(new_balance)) - balance_before
        if amount > 0:
            transaction = await service.add_credit(uid, amount, reason or "Admin adjustment", reference_id=f"admin-adjust:{user_id}:{datetime.now(UTC).timestamp()}")
            txn_type = "credit"
        elif amount < 0:
            try:
                transaction = await service.deduct_credit(uid, abs(amount), reason or "Admin adjustment", reference_id=f"admin-adjust:{user_id}:{datetime.now(UTC).timestamp()}")
            except InsufficientCredits as exc:
                return {"error": "Insufficient balance", "required": float(exc.required), "balance": float(exc.balance)}
            txn_type = "debit"
        else:
            return {"error": "No balance adjustment required", "balance": float(balance_before)}
        wallet = await service.get_wallet(uid)

        return {
            "transaction_id": str(transaction.id) if transaction.id else "",
            "type": txn_type,
            "amount": abs(amount),
            "balance_before": float(balance_before),
            "balance_after": float(wallet.balance),
            "reason": reason,
        }

    async def freeze_wallet(self, user_id: str, reason: str | None = None) -> dict[str, Any]:
        result = await self.db.execute(select(Wallet).where(Wallet.user_id == user_id))
        wallet = result.scalar_one_or_none()
        if wallet is None:
            return {"error": "Wallet not found"}

        freeze = WalletFreeze(user_id=user_id, wallet_id=wallet.id, reason=reason or "Admin freeze")
        self.db.add(freeze)
        await self.db.flush()
        return {"success": True, "message": "Wallet frozen"}

    async def unfreeze_wallet(self, user_id: str, reason: str | None = None) -> dict[str, Any]:
        result = await self.db.execute(select(WalletFreeze).where(WalletFreeze.user_id == user_id, WalletFreeze.is_frozen == True))
        freeze = result.scalar_one_or_none()
        if freeze:
            freeze.is_frozen = False
            await self.db.flush()
        return {"success": True, "message": "Wallet unfrozen"}

    async def list_wallets(self, limit: int = 50, offset: int = 0, status: str | None = None) -> list[dict[str, Any]]:
        stmt = select(Wallet)
        if status:
            stmt = stmt.where(Wallet.status == status)
        stmt = stmt.limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        wallets = result.scalars().all()
        output = []
        for w in wallets:
            user_result = await self.db.execute(select(User).where(User.id == w.user_id))
            user = user_result.scalar_one_or_none()
            output.append({
                "id": str(w.id) if w.id else None,
                "user_id": str(w.user_id) if w.user_id else None,
                "user_name": user.name if user else None,
                "org_name": None,
                "balance": float(w.balance),
                "currency": "usd",
                "status": w.status,
                "created_at": w.created_at.isoformat() if w.created_at else "",
                "updated_at": w.updated_at.isoformat() if w.updated_at else "",
            })
        return output

    async def list_transactions(self, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        result = await self.db.execute(select(WalletTransaction).order_by(WalletTransaction.created_at.desc()).limit(limit).offset(offset))
        rows = result.scalars().all()
        output = []
        for row in rows:
            user_result = await self.db.execute(select(User).where(User.id == row.user_id))
            user = user_result.scalar_one_or_none()
            org_result = await self.db.execute(select(Organization).where(Organization.id == row.user_id))
            org = org_result.scalar_one_or_none()
            output.append({
                "id": str(row.id) if row.id else None,
                "wallet_id": str(row.wallet_id) if row.wallet_id else None,
                "user_id": str(row.user_id) if row.user_id else None,
                "user_name": user.name if user else None,
                "org_name": org.name if org else None,
                "type": row.type,
                "amount": float(row.amount),
                "balance_after": float(row.balance_after),
                "reason": row.reason,
                "created_at": row.created_at.isoformat() if row.created_at else "",
            })
        return output

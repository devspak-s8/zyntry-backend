from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.provider_funding import (
    ProviderFundingAccount,
    ProviderFundingEvent,
    ProviderFundingMode,
    ProviderFundingStatus,
)


def money(value: Decimal | int | float | str | None) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("0.000001"))


class ProviderFundingService:
    """Monitor provider balances without mixing them with customer wallets.

    Provider billing APIs are not uniform and most model APIs do not expose a
    safe generic top-up endpoint. This service therefore supports provider-side
    auto-recharge as the default automatic mode, records provider liabilities,
    and exposes an explicit adapter boundary for future provider billing APIs.
    It never credits a provider by debiting a customer wallet.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_accounts(self) -> list[ProviderFundingAccount]:
        result = await self.session.execute(
            select(ProviderFundingAccount).order_by(ProviderFundingAccount.provider.asc())
        )
        return list(result.scalars().all())

    async def get_account(self, provider: str) -> ProviderFundingAccount | None:
        return await self.session.scalar(
            select(ProviderFundingAccount).where(
                ProviderFundingAccount.provider == provider.strip().lower()
            )
        )

    async def configure(
        self,
        provider: str,
        *,
        account_label: str | None = None,
        currency: str = "usd",
        funding_mode: str = ProviderFundingMode.MANUAL,
        monitor_enabled: bool = True,
        auto_top_up_enabled: bool = False,
        current_balance: Decimal | None = None,
        estimated_balance: Decimal = Decimal("0"),
        minimum_balance: Decimal = Decimal("0"),
        target_balance: Decimal = Decimal("0"),
        max_top_up: Decimal = Decimal("0"),
        daily_top_up_limit: Decimal = Decimal("0"),
        payment_method_ref: str | None = None,
        external_account_ref: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderFundingAccount:
        normalized = provider.strip().lower()
        mode = funding_mode.strip().lower()
        if mode not in {
            ProviderFundingMode.MANUAL,
            ProviderFundingMode.PROVIDER_AUTO_RECHARGE,
            ProviderFundingMode.ZYNTRY_MANAGED,
        }:
            raise ValueError("Unsupported provider funding mode")
        minimum = money(minimum_balance)
        target = money(target_balance)
        maximum = money(max_top_up)
        daily_limit = money(daily_top_up_limit)
        if minimum < 0 or target < minimum or maximum < 0 or daily_limit < maximum:
            raise ValueError(
                "Funding thresholds must satisfy 0 <= minimum <= target and max_top_up <= daily_top_up_limit"
            )
        if auto_top_up_enabled and mode == ProviderFundingMode.MANUAL:
            raise ValueError("Automatic funding requires provider_auto_recharge or zyntry_managed mode")
        account = await self.get_account(normalized)
        if account is None:
            account = ProviderFundingAccount(
                provider=normalized,
                account_label=account_label or normalized.title(),
                currency=currency.lower(),
                funding_mode=mode,
                monitor_enabled=monitor_enabled,
                auto_top_up_enabled=auto_top_up_enabled,
                current_balance=current_balance,
                estimated_balance=money(
                    current_balance if current_balance is not None else estimated_balance
                ),
                minimum_balance=minimum,
                target_balance=target,
                max_top_up=maximum,
                daily_top_up_limit=daily_limit,
                payment_method_ref=payment_method_ref,
                external_account_ref=external_account_ref,
                metadata_=metadata or {},
            )
            self.session.add(account)
        else:
            account.account_label = account_label or account.account_label
            account.currency = currency.lower()
            account.funding_mode = mode
            account.monitor_enabled = monitor_enabled
            account.auto_top_up_enabled = auto_top_up_enabled
            if current_balance is not None:
                account.current_balance = money(current_balance)
                account.estimated_balance = money(current_balance)
            elif account.current_balance is None:
                account.estimated_balance = money(estimated_balance)
            account.minimum_balance = minimum
            account.target_balance = target
            account.max_top_up = maximum
            account.daily_top_up_limit = daily_limit
            account.payment_method_ref = payment_method_ref
            account.external_account_ref = external_account_ref
            account.metadata_ = metadata or account.metadata_ or {}
        await self.session.commit()
        await self.session.refresh(account)
        return account

    async def record_provider_cost(
        self,
        provider: str,
        amount: Decimal,
        *,
        request_id: str | None = None,
        model: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderFundingAccount | None:
        cost = money(amount)
        if cost <= 0:
            return None
        normalized = provider.strip().lower()
        account = await self.session.scalar(
            select(ProviderFundingAccount)
            .where(ProviderFundingAccount.provider == normalized)
            .with_for_update()
        )
        if account is None:
            return None
        key = f"usage:{request_id}" if request_id else f"usage:{uuid.uuid4()}"
        existing = await self.session.scalar(
            select(ProviderFundingEvent).where(ProviderFundingEvent.idempotency_key == key)
        )
        if existing is not None:
            return account
        account.estimated_balance = max(
            Decimal("0"), money(account.estimated_balance) - cost
        )
        if account.current_balance is not None:
            account.current_balance = max(
                Decimal("0"), money(account.current_balance) - cost
            )
        account.status = self._balance_status(account)
        self.session.add(
            ProviderFundingEvent(
                account_id=account.id,
                provider=normalized,
                event_type="usage_cost",
                status="recorded",
                amount=cost,
                balance_after=account.estimated_balance,
                request_id=request_id,
                idempotency_key=key,
                metadata_={"model": model, **(metadata or {})},
            )
        )
        await self.session.commit()
        return account

    async def check_account(self, account: ProviderFundingAccount) -> dict[str, Any]:
        now = datetime.now(UTC)
        account.last_checked_at = now
        if not account.monitor_enabled:
            account.status = ProviderFundingStatus.DISABLED
            await self.session.commit()
            return self.serialize(account)
        balance = self._effective_balance(account)
        if balance > account.minimum_balance:
            account.status = ProviderFundingStatus.HEALTHY
            account.last_error = None
            await self.session.commit()
            return self.serialize(account)

        if (
            account.auto_top_up_enabled
            and account.funding_mode == ProviderFundingMode.PROVIDER_AUTO_RECHARGE
        ):
            account.status = ProviderFundingStatus.AWAITING_RECHARGE
            account.last_error = (
                "Provider-side auto-recharge must be enabled for this account; "
                "Zyntry does not debit customer wallets or store card data."
            )
            event_status = "awaiting_provider_recharge"
        elif account.auto_top_up_enabled and account.funding_mode == ProviderFundingMode.ZYNTRY_MANAGED:
            account.status = ProviderFundingStatus.FUNDING_UNSUPPORTED
            account.last_error = (
                "No safe provider top-up adapter is configured. "
                "Enable provider-side auto-recharge or add a verified billing adapter."
            )
            event_status = "adapter_required"
        else:
            account.status = ProviderFundingStatus.LOW
            account.last_error = "Provider balance is at or below the configured minimum."
            event_status = "low_balance"

        self.session.add(
            ProviderFundingEvent(
                account_id=account.id,
                provider=account.provider,
                event_type="funding_check",
                status=event_status,
                amount=Decimal("0"),
                balance_after=balance,
                idempotency_key=f"check:{account.provider}:{now.isoformat()}",
                error=account.last_error,
            )
        )
        await self.session.commit()
        return self.serialize(account)

    async def check_all(self) -> list[dict[str, Any]]:
        accounts = await self.list_accounts()
        return [await self.check_account(account) for account in accounts]

    async def reconcile(
        self,
        provider: str,
        balance: Decimal,
        *,
        external_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProviderFundingAccount:
        account = await self.get_account(provider)
        if account is None:
            raise ValueError("Provider funding account is not configured")
        actual = money(balance)
        if actual < 0:
            raise ValueError("Provider balance cannot be negative")
        account.current_balance = actual
        account.estimated_balance = actual
        account.status = self._balance_status(account)
        account.last_error = None
        self.session.add(
            ProviderFundingEvent(
                account_id=account.id,
                provider=account.provider,
                event_type="balance_reconciled",
                status="recorded",
                amount=actual,
                balance_after=actual,
                idempotency_key=f"reconcile:{account.provider}:{uuid.uuid4()}",
                external_id=external_id,
                metadata_=metadata or {},
            )
        )
        await self.session.commit()
        await self.session.refresh(account)
        return account

    @staticmethod
    def _effective_balance(account: ProviderFundingAccount) -> Decimal:
        if account.current_balance is not None:
            return money(account.current_balance)
        return money(account.estimated_balance)

    @classmethod
    def _balance_status(cls, account: ProviderFundingAccount) -> str:
        return (
            ProviderFundingStatus.LOW
            if cls._effective_balance(account) <= money(account.minimum_balance)
            else ProviderFundingStatus.HEALTHY
        )

    @staticmethod
    def serialize(account: ProviderFundingAccount) -> dict[str, Any]:
        return {
            "id": str(account.id),
            "provider": account.provider,
            "account_label": account.account_label,
            "currency": account.currency,
            "funding_mode": account.funding_mode,
            "monitor_enabled": account.monitor_enabled,
            "auto_top_up_enabled": account.auto_top_up_enabled,
            "current_balance": float(account.current_balance) if account.current_balance is not None else None,
            "estimated_balance": float(account.estimated_balance),
            "minimum_balance": float(account.minimum_balance),
            "target_balance": float(account.target_balance),
            "max_top_up": float(account.max_top_up),
            "daily_top_up_limit": float(account.daily_top_up_limit),
            "daily_top_up_total": float(account.daily_top_up_total),
            "payment_method_configured": bool(account.payment_method_ref),
            "external_account_ref": account.external_account_ref,
            "status": account.status,
            "last_checked_at": account.last_checked_at.isoformat() if account.last_checked_at else None,
            "last_top_up_at": account.last_top_up_at.isoformat() if account.last_top_up_at else None,
            "last_error": account.last_error,
        }

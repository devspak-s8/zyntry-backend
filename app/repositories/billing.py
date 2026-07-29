from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select, func

from app.models.billing import Budget, PricingRule, UsageLog, Wallet, WalletTransaction
from app.repositories.base import BaseRepository


class WalletRepository(BaseRepository[Wallet]):
    model = Wallet

    async def get_by_user(self, user_id: uuid.UUID) -> Wallet | None:
        result = await self.session.execute(
            select(self.model).where(self.model.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_for_update(self, wallet_id: uuid.UUID) -> Wallet | None:
        result = await self.session.execute(
            select(self.model)
            .where(self.model.id == wallet_id)
            .with_for_update()
        )
        return result.scalar_one_or_none()


class WalletTransactionRepository(BaseRepository[WalletTransaction]):
    model = WalletTransaction

    async def list_for_wallet(self, wallet_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[WalletTransaction]:
        result = await self.session.execute(
            select(self.model)
            .where(self.model.wallet_id == wallet_id)
            .order_by(self.model.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def get_by_reference(self, reference_id: str) -> WalletTransaction | None:
        result = await self.session.execute(
            select(self.model).where(self.model.reference_id == reference_id)
        )
        return result.scalar_one_or_none()


class PricingRuleRepository(BaseRepository[PricingRule]):
    model = PricingRule

    async def list_active(self, provider: str | None = None, operation: str | None = None) -> list[PricingRule]:
        stmt = select(self.model).where(self.model.active == True)
        if provider:
            stmt = stmt.where(self.model.provider == provider)
        if operation:
            stmt = stmt.where(self.model.operation == operation)
        result = await self.session.execute(stmt.order_by(self.model.created_at.desc()))
        return list(result.scalars().all())

    async def list_by_provider(self, provider: str) -> list[PricingRule]:
        result = await self.session.execute(
            select(self.model).where(
                self.model.provider == provider,
                self.model.active == True,
            )
        )
        return list(result.scalars().all())

    async def get_rule(self, provider: str, operation: str, model: str | None = None) -> PricingRule | None:
        stmt = select(self.model).where(
            self.model.provider == provider,
            self.model.operation == operation,
            self.model.active == True,
        )
        if model:
            stmt = stmt.where(self.model.model == model)
        else:
            stmt = stmt.where(self.model.model.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class UsageLogRepository(BaseRepository[UsageLog]):
    model = UsageLog

    async def list_for_user(self, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[UsageLog]:
        result = await self.session.execute(
            select(self.model)
            .where(self.model.user_id == user_id)
            .order_by(self.model.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def list_for_project(self, project_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[UsageLog]:
        result = await self.session.execute(
            select(self.model)
            .where(self.model.project_id == project_id)
            .order_by(self.model.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def sum_for_user(self, user_id: uuid.UUID) -> dict:
        result = await self.session.execute(
            select(
                func.coalesce(func.sum(self.model.cost), Decimal("0")).label("total_cost"),
                func.coalesce(func.sum(self.model.requests), 0).label("total_requests"),
                func.coalesce(func.sum(self.model.input_tokens), 0).label("total_input_tokens"),
                func.coalesce(func.sum(self.model.output_tokens), 0).label("total_output_tokens"),
                func.coalesce(func.sum(self.model.embedding_tokens), 0).label("total_embedding_tokens"),
                func.coalesce(func.sum(self.model.vector_searches), 0).label("total_vector_searches"),
                func.coalesce(func.sum(self.model.storage_bytes), 0).label("total_storage_bytes"),
                func.coalesce(func.sum(self.model.latency_ms), 0).label("total_latency_ms"),
            ).where(self.model.user_id == user_id)
        )
        row = result.mappings().one()
        return dict(row)

    async def sum_by_provider(self, user_id: uuid.UUID) -> dict[str, Decimal]:
        from decimal import Decimal as D
        result = await self.session.execute(
            select(self.model.provider, func.coalesce(func.sum(self.model.cost), D("0")))
            .where(self.model.user_id == user_id)
            .group_by(self.model.provider)
        )
        return {row[0]: row[1] for row in result.all()}

    async def sum_by_model(self, user_id: uuid.UUID) -> dict[str, Decimal]:
        from decimal import Decimal as D
        result = await self.session.execute(
            select(self.model.model, func.coalesce(func.sum(self.model.cost), D("0")))
            .where(self.model.user_id == user_id)
            .group_by(self.model.model)
        )
        return {row[0]: row[1] for row in result.all()}

    async def sum_by_operation(self, user_id: uuid.UUID) -> dict[str, Decimal]:
        from decimal import Decimal as D
        result = await self.session.execute(
            select(self.model.operation, func.coalesce(func.sum(self.model.cost), D("0")))
            .where(self.model.user_id == user_id)
            .group_by(self.model.operation)
        )
        return {row[0]: row[1] for row in result.all()}


class BudgetRepository(BaseRepository[Budget]):
    model = Budget

    async def get_by_user(self, user_id: uuid.UUID) -> Budget | None:
        result = await self.session.execute(
            select(self.model).where(self.model.user_id == user_id)
        )
        return result.scalar_one_or_none()

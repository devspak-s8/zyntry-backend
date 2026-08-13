from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.models.billing import (
    Budget,
    TransactionType,
    UsageLog,
    Wallet,
    WalletStatus,
    WalletTransaction,
)
from app.repositories import UnitOfWork
from app.schemas.billing import (
    BudgetCreate,
    BudgetUpdate,
    EstimateCostRequest,
    EstimateCostResponse,
    InsufficientCreditsError,
    RefundRequest,
    WalletRead,
    WalletTransactionRead,
)


class InsufficientCredits(Exception):
    def __init__(self, required: Decimal, balance: Decimal) -> None:
        self.required = required
        self.balance = balance
        self.error = InsufficientCreditsError(required=required, balance=balance)


class BillingService:
    def __init__(self, session) -> None:
        self.session = session
        self.uow = UnitOfWork(session)

    async def get_wallet(self, user_id: uuid.UUID) -> Wallet:
        wallet = await self.uow.wallets.get_by_user(user_id)
        if wallet is None:
            try:
                wallet = await self.uow.wallets.create(
                    user_id=user_id,
                    balance=Decimal("0.0000"),
                    currency="usd",
                    status=WalletStatus.ACTIVE,
                )
                await self.uow.commit()
            except IntegrityError:
                await self.uow.rollback()
                wallet = await self.uow.wallets.get_by_user(user_id)
                if wallet is None:
                    raise
        return wallet

    async def create_wallet(self, user_id: uuid.UUID, currency: str = "usd") -> Wallet:
        existing = await self.uow.wallets.get_by_user(user_id)
        if existing:
            return existing
        try:
            wallet = await self.uow.wallets.create(
                user_id=user_id,
                balance=Decimal("0.0000"),
                currency=currency,
                status=WalletStatus.ACTIVE,
            )
            await self.uow.commit()
            return wallet
        except IntegrityError:
            await self.uow.rollback()
            return await self.uow.wallets.get_by_user(user_id)

    async def add_credit(self, user_id: uuid.UUID, amount: Decimal, reason: str, reference_id: str | None = None, metadata: dict | None = None) -> WalletTransaction:
        if amount <= Decimal("0"):
            raise ValueError("Credit amount must be positive")

        wallet = await self.get_wallet(user_id)
        if wallet.status != WalletStatus.ACTIVE:
            raise ValueError(f"Wallet is {wallet.status}")

        locked_wallet = await self.uow.wallets.get_for_update(wallet.id)
        if locked_wallet is None:
            raise ValueError("Wallet not found")

        balance_before = locked_wallet.balance
        balance_after = balance_before + amount

        transaction = await self.uow.wallet_transactions.create(
            wallet_id=locked_wallet.id,
            type=TransactionType.CREDIT,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reason=reason,
            reference_id=reference_id,
            metadata=metadata or {},
        )
        locked_wallet.balance = balance_after
        budget = await self.uow.budgets.get_by_user(user_id)
        if budget and budget.limit_reached and balance_after > Decimal("0"):
            await self.uow.budgets.update(budget, limit_reached=False, current_spend=Decimal("0"))
        await self.uow.commit()
        return transaction

    async def deduct_credit(self, user_id: uuid.UUID, amount: Decimal, reason: str, reference_id: str | None = None, metadata: dict | None = None) -> WalletTransaction:
        if amount <= Decimal("0"):
            raise ValueError("Deduction amount must be positive")

        wallet = await self.get_wallet(user_id)
        if wallet.status != WalletStatus.ACTIVE:
            raise ValueError(f"Wallet is {wallet.status}")

        locked_wallet = await self.uow.wallets.get_for_update(wallet.id)
        if locked_wallet is None:
            raise ValueError("Wallet not found")

        if locked_wallet.balance < amount:
            raise InsufficientCredits(required=amount, balance=locked_wallet.balance)

        balance_before = locked_wallet.balance
        balance_after = balance_before - amount

        transaction = await self.uow.wallet_transactions.create(
            wallet_id=locked_wallet.id,
            type=TransactionType.DEBIT,
            amount=amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reason=reason,
            reference_id=reference_id,
            metadata=metadata or {},
        )
        locked_wallet.balance = balance_after
        await self._update_budget_spend(user_id, amount)
        await self.uow.commit()
        return transaction

    async def refund_transaction(self, user_id: uuid.UUID, body: RefundRequest) -> WalletTransaction:
        original = await self.session.get(WalletTransaction, body.transaction_id)
        if original is None:
            raise ValueError("Transaction not found")

        if original.type != TransactionType.DEBIT:
            raise ValueError("Only debit transactions can be refunded")

        wallet = await self.uow.wallets.get_by_user(user_id)
        if wallet is None or wallet.id != original.wallet_id:
            raise ValueError("Wallet mismatch")

        locked_wallet = await self.uow.wallets.get_for_update(wallet.id)
        if locked_wallet is None:
            raise ValueError("Wallet not found")

        balance_before = locked_wallet.balance
        balance_after = balance_before + original.amount

        transaction = await self.uow.wallet_transactions.create(
            wallet_id=locked_wallet.id,
            type=TransactionType.REFUND,
            amount=original.amount,
            balance_before=balance_before,
            balance_after=balance_after,
            reason=body.reason,
            reference_id=str(original.id),
            metadata={"original_transaction_id": str(original.id)},
        )
        locked_wallet.balance = balance_after
        budget = await self.uow.budgets.get_by_user(user_id)
        if budget and budget.limit_reached and balance_after > Decimal("0"):
            await self.uow.budgets.update(budget, limit_reached=False, current_spend=budget.current_spend - original.amount)
        await self.uow.commit()
        return transaction

    async def calculate_cost(self, provider: str, model: str, operation: str, input_tokens: int = 0, output_tokens: int = 0, embedding_tokens: int = 0, vector_searches: int = 0, storage_bytes: int = 0, requests: int = 1) -> Decimal:
        total = Decimal("0.0000")

        rules = await self.uow.pricing_rules.list_by_provider(provider)
        rule_map = {(r.operation, r.model): r for r in rules}

        def lookup(op: str, mdl: str | None) -> PricingRule | None:
            return rule_map.get((op, mdl)) or rule_map.get((op, None))

        token_operations = {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "embeddings": embedding_tokens,
        }

        for op, count in token_operations.items():
            if count > 0:
                rule = lookup(op, model)
                if rule:
                    total += rule.price_per_unit * Decimal(count)

        if vector_searches > 0:
            rule = lookup("vector_search", model)
            if rule:
                total += rule.price_per_unit * Decimal(vector_searches)

        if storage_bytes > 0:
            rule = lookup("storage", model)
            if rule:
                total += rule.price_per_unit * Decimal(storage_bytes)

        if requests > 0 and operation not in ("input_tokens", "output_tokens", "embeddings", "vector_search", "storage"):
            rule = lookup(operation, model)
            if rule:
                total += rule.price_per_unit * Decimal(requests)

        return total

    async def estimate_request_cost(self, body: EstimateCostRequest) -> EstimateCostResponse:
        rules = await self.uow.pricing_rules.list_by_provider(body.provider)
        rule_map = {(r.operation, r.model): r for r in rules}

        def lookup(op: str, mdl: str | None) -> PricingRule | None:
            return rule_map.get((op, mdl)) or rule_map.get((op, None))

        cost = Decimal("0.0000")
        breakdown: dict[str, Decimal] = {}

        if body.input_tokens > 0:
            rule = lookup("input_tokens", body.model)
            if rule:
                cost += rule.price_per_unit * Decimal(body.input_tokens)
                breakdown["input_tokens"] = rule.price_per_unit * Decimal(body.input_tokens)

        if body.output_tokens > 0:
            rule = lookup("output_tokens", body.model)
            if rule:
                cost += rule.price_per_unit * Decimal(body.output_tokens)
                breakdown["output_tokens"] = rule.price_per_unit * Decimal(body.output_tokens)

        if body.embedding_tokens > 0:
            rule = lookup("embeddings", body.model)
            if rule:
                cost += rule.price_per_unit * Decimal(body.embedding_tokens)
                breakdown["embeddings"] = rule.price_per_unit * Decimal(body.embedding_tokens)

        return EstimateCostResponse(estimated_cost=cost, currency="usd", breakdown=breakdown)

    async def record_usage(
        self,
        user_id: uuid.UUID,
        provider: str,
        model: str,
        operation: str,
        cost: Decimal,
        project_id: uuid.UUID | None = None,
        runtime_id: uuid.UUID | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        embedding_tokens: int = 0,
        vector_searches: int = 0,
        storage_bytes: int = 0,
        requests: int = 1,
        latency_ms: int | None = None,
        metadata: dict | None = None,
    ) -> UsageLog:
        log = await self.uow.usage_logs.create(
            user_id=user_id,
            project_id=project_id,
            runtime_id=runtime_id,
            provider=provider,
            model=model,
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            embedding_tokens=embedding_tokens,
            vector_searches=vector_searches,
            storage_bytes=storage_bytes,
            requests=requests,
            latency_ms=latency_ms,
            cost=cost,
            metadata=metadata or {},
        )
        analytics_event = None
        if project_id is not None:
            analytics_event = await self.uow.analytics.create(
                metric="runtime_invocation",
                quantity=input_tokens + output_tokens + embedding_tokens,
                model=model,
                provider=provider,
                project_id=project_id,
                metadata={
                    **(metadata or {}),
                    "runtime_id": str(runtime_id) if runtime_id else None,
                    "operation": operation,
                    "requests": requests,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "embedding_tokens": embedding_tokens,
                    "latency_ms": latency_ms,
                    "cost": str(cost),
                },
            )
        await self.uow.commit()
        if analytics_event is not None:
            from app.core.runtime_events import publish_runtime_event

            await publish_runtime_event(
                {
                    "type": "analytics.usage.updated",
                    "id": str(analytics_event.id),
                    "project_id": str(project_id),
                    "runtime_id": str(runtime_id) if runtime_id else None,
                    "metric": analytics_event.metric,
                    "quantity": analytics_event.quantity,
                    "provider": provider,
                    "model": model,
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "latency_ms": latency_ms,
                    "cost": str(cost),
                    "created_at": analytics_event.created_at.isoformat(),
                }
            )
        return log

    async def check_budget(self, user_id: uuid.UUID, estimated_cost: Decimal) -> bool:
        budget = await self.uow.budgets.get_by_user(user_id)
        if budget is None or budget.monthly_limit is None:
            return True

        projected_spend = budget.current_spend + estimated_cost
        if projected_spend >= budget.monthly_limit:
            if not budget.limit_reached:
                await self.uow.budgets.update(budget, limit_reached=True)
                await self.uow.commit()
                await self._send_budget_notification(user_id, "limit_reached", budget.monthly_limit)
            return False

        if projected_spend >= budget.monthly_limit * Decimal("0.9") and not budget.warning_90_sent:
            await self.uow.budgets.update(budget, warning_90_sent=True)
            await self.uow.commit()
            await self._send_budget_notification(user_id, "warning_90", budget.monthly_limit)

        if projected_spend >= budget.monthly_limit * Decimal("0.8") and not budget.warning_80_sent:
            await self.uow.budgets.update(budget, warning_80_sent=True)
            await self.uow.commit()
            await self._send_budget_notification(user_id, "warning_80", budget.monthly_limit)

        return True

    async def _update_budget_spend(self, user_id: uuid.UUID, amount: Decimal) -> None:
        budget = await self.uow.budgets.get_by_user(user_id)
        if budget is None or budget.monthly_limit is None:
            return

        new_spend = budget.current_spend + amount
        await self.uow.budgets.update(budget, current_spend=new_spend)

        if new_spend >= budget.monthly_limit and not budget.limit_reached:
            await self.uow.budgets.update(budget, limit_reached=True)
            await self._send_budget_notification(user_id, "limit_reached", budget.monthly_limit)
        elif new_spend >= budget.monthly_limit * Decimal("0.9") and not budget.warning_90_sent:
            await self.uow.budgets.update(budget, warning_90_sent=True)
            await self._send_budget_notification(user_id, "warning_90", budget.monthly_limit)
        elif new_spend >= budget.monthly_limit * Decimal("0.8") and not budget.warning_80_sent:
            await self.uow.budgets.update(budget, warning_80_sent=True)
            await self._send_budget_notification(user_id, "warning_80", budget.monthly_limit)

    async def _send_budget_notification(self, user_id: uuid.UUID, event_type: str, limit: Decimal) -> None:
        from app.services.notifications import NotificationService
        from app.tasks.billing import send_budget_notification_task

        service = NotificationService(self.session)
        if event_type == "limit_reached":
            await service.create(
                user_id=user_id,
                type="usage.limit.reached",
                title="Budget Limit Reached",
                message=f"Your monthly budget of ${limit:.2f} has been reached. AI requests will be rejected until your spend resets.",
            )
            send_budget_notification_task.delay(str(user_id), event_type, str(limit))
        elif event_type == "warning_90":
            await service.create(
                user_id=user_id,
                type="credits.low",
                title="Budget Warning: 90% Used",
                message=f"You have used 90% of your monthly budget (${limit:.2f}). Consider increasing your limit.",
            )
            send_budget_notification_task.delay(str(user_id), event_type, str(limit))
        elif event_type == "warning_80":
            await service.create(
                user_id=user_id,
                type="credits.low",
                title="Budget Warning: 80% Used",
                message=f"You have used 80% of your monthly budget (${limit:.2f}).",
            )
            send_budget_notification_task.delay(str(user_id), event_type, str(limit))

    async def check_auto_top_up(self, user_id: uuid.UUID) -> bool:
        budget = await self.uow.budgets.get_by_user(user_id)
        if not budget or not budget.auto_top_up_enabled or not budget.auto_top_up_threshold or not budget.auto_top_up_amount:
            return False

        wallet = await self.get_wallet(user_id)
        if wallet.balance < budget.auto_top_up_threshold:
            from app.tasks.billing import process_auto_top_up
            process_auto_top_up.delay(str(user_id))
            return True
        return False

    async def get_wallet_read(self, user_id: uuid.UUID) -> WalletRead:
        wallet = await self.get_wallet(user_id)
        return WalletRead(
            id=wallet.id,
            user_id=wallet.user_id,
            balance=wallet.balance,
            currency=wallet.currency,
            status=wallet.status,
            created_at=wallet.created_at,
            updated_at=wallet.updated_at,
        )

    async def get_transactions(self, user_id: uuid.UUID, limit: int = 50, offset: int = 0) -> list[WalletTransactionRead]:
        wallet = await self.get_wallet(user_id)
        transactions = await self.uow.wallet_transactions.list_for_wallet(wallet.id, limit=limit, offset=offset)
        return [
            WalletTransactionRead(
                id=t.id,
                wallet_id=t.wallet_id,
                type=t.type,
                amount=t.amount,
                balance_before=t.balance_before,
                balance_after=t.balance_after,
                reason=t.reason,
                reference_id=t.reference_id,
                metadata=t.metadata_,
                created_at=t.created_at,
            )
            for t in transactions
        ]

    async def get_usage_summary(self, user_id: uuid.UUID) -> dict:
        totals = await self.uow.usage_logs.sum_for_user(user_id)
        by_provider = await self.uow.usage_logs.sum_by_provider(user_id)
        by_model = await self.uow.usage_logs.sum_by_model(user_id)
        by_operation = await self.uow.usage_logs.sum_by_operation(user_id)
        return {
            "total_cost": totals.get("total_cost", Decimal("0")),
            "total_requests": totals.get("total_requests", 0),
            "total_input_tokens": totals.get("total_input_tokens", 0),
            "total_output_tokens": totals.get("total_output_tokens", 0),
            "total_embedding_tokens": totals.get("total_embedding_tokens", 0),
            "total_vector_searches": totals.get("total_vector_searches", 0),
            "total_storage_bytes": totals.get("total_storage_bytes", 0),
            "total_latency_ms": totals.get("total_latency_ms", 0),
            "by_provider": by_provider,
            "by_model": by_model,
            "by_operation": by_operation,
        }

    async def get_budget(self, user_id: uuid.UUID) -> Budget | None:
        return await self.uow.budgets.get_by_user(user_id)

    async def create_or_update_budget(self, user_id: uuid.UUID, body: BudgetCreate) -> Budget:
        existing = await self.uow.budgets.get_by_user(user_id)
        if existing:
            updated = await self.uow.budgets.update(
                existing,
                monthly_limit=body.monthly_limit,
                auto_top_up_enabled=body.auto_top_up_enabled,
                auto_top_up_threshold=body.auto_top_up_threshold,
                auto_top_up_amount=body.auto_top_up_amount,
            )
            await self.uow.commit()
            return updated

        budget = await self.uow.budgets.create(
            user_id=user_id,
            monthly_limit=body.monthly_limit,
            auto_top_up_enabled=body.auto_top_up_enabled,
            auto_top_up_threshold=body.auto_top_up_threshold,
            auto_top_up_amount=body.auto_top_up_amount,
            current_spend=Decimal("0.0000"),
        )
        await self.uow.commit()
        return budget

    async def update_budget(self, user_id: uuid.UUID, body: BudgetUpdate) -> Budget | None:
        budget = await self.uow.budgets.get_by_user(user_id)
        if budget is None:
            return None

        update_data = body.model_dump(exclude_none=True)
        updated = await self.uow.budgets.update(budget, **update_data)
        await self.uow.commit()
        return updated

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings


def _normalize_async_url(url: str) -> str:
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


engine = create_async_engine(
    _normalize_async_url(settings.DATABASE_URL),
    echo=False,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=0,
)
session_factory = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


async def get_derived_spend(session: AsyncSession) -> dict[str, Decimal]:
    result = await session.execute(
        text("""
            SELECT w.user_id::text AS user_id,
                   COALESCE(SUM(
                       CASE
                           WHEN wt.type = 'debit' THEN wt.amount
                           WHEN wt.type = 'refund' THEN -wt.amount
                           ELSE 0
                       END
                   ), 0) AS derived_spend
            FROM wallet_transactions wt
            JOIN wallets w ON w.id = wt.wallet_id
            GROUP BY w.user_id
        """)
    )
    return {row.user_id: row.derived_spend for row in result.all()}


async def get_budgets(session: AsyncSession) -> dict[str, tuple[Decimal, str]]:
    result = await session.execute(
        text("""
            SELECT user_id::text AS user_id, current_spend, id::text AS id
            FROM budgets
        """)
    )
    return {row.user_id: (row.current_spend, row.id) for row in result.all()}


async def create_snapshot(session: AsyncSession, dry_run: bool) -> str:
    table_name = f"budgets_backup_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
    sql = f"CREATE TABLE {table_name} AS SELECT * FROM budgets"
    if dry_run:
        print(f"[dry-run] Would create snapshot table: {table_name}")
        return table_name
    await session.execute(text(sql))
    await session.commit()
    print(f"Created snapshot table: {table_name}")
    return table_name


async def reconcile(dry_run: bool, snapshot: bool) -> None:
    async with session_factory() as session:
        derived = await get_derived_spend(session)
        stored = await get_budgets(session)

        if not stored:
            print("No budget records found. Nothing to do.")
            return

        if snapshot:
            await create_snapshot(session, dry_run)

        all_user_ids = sorted(set(stored.keys()) | set(derived.keys()))
        drift_count = 0
        total_drift = Decimal("0")
        rows: list[dict] = []

        for user_id in all_user_ids:
            derived_spend = derived.get(user_id, Decimal("0"))
            stored_spend, budget_id = stored.get(user_id, (Decimal("0"), "N/A"))
            diff = derived_spend - stored_spend
            if diff != 0:
                drift_count += 1
                total_drift += abs(diff)
            rows.append({
                "user_id": user_id,
                "budget_id": budget_id,
                "derived": derived_spend,
                "stored": stored_spend,
                "diff": diff,
            })

        header = f"{'user_id':<36} {'budget_id':<38} {'derived':>12} {'stored':>12} {'diff':>12}"
        print(header)
        print("-" * len(header))
        for row in rows:
            flag = " <-- DRIFT" if row["diff"] != 0 else ""
            print(
                f"{row['user_id']:<36} {row['budget_id']:<38} "
                f"{float(row['derived']):>12.4f} {float(row['stored']):>12.4f} "
                f"{float(row['diff']):>+12.4f}{flag}"
            )

        print()
        print(f"Total users:    {len(rows)}")
        print(f"Drifted users:  {drift_count}")
        print(f"Total abs drift:{float(total_drift):>12.4f}")

        if dry_run:
            print("\n[dry-run] No changes written. Re-run with --write to apply.")
            return

        if drift_count == 0:
            print("\nNo drift found. Nothing to write.")
            return

        updated = 0
        for row in rows:
            if row["diff"] == 0:
                continue
            budget_id = row["budget_id"]
            if budget_id == "N/A":
                print(f"  SKIP user {row['user_id']}: no budget record")
                continue
            await session.execute(
                text("UPDATE budgets SET current_spend = :spend WHERE id = :id"),
                {"spend": float(row["derived"]), "id": budget_id},
            )
            updated += 1

        await session.commit()
        print(f"\nUpdated {updated} budget records to match derived spend.")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Reconcile budget.current_spend against wallet_transactions"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply corrections (default is dry-run)",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Create a budgets_backup_* table before writing",
    )
    args = parser.parse_args()

    await reconcile(dry_run=not args.write, snapshot=args.snapshot)


if __name__ == "__main__":
    asyncio.run(main())

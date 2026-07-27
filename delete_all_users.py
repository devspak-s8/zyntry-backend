import asyncio
import sys

sys.path.insert(0, "C:/Users/apati/Zyntry/backend")

from app.core.database import engine, AsyncSession
from sqlalchemy import text


TRUNCATE_ORDER = [
    "sync_schedules",
    "sync_jobs",
    "runtime_build_logs",
    "runtime_build_chunks",
    "runtimes",
    "embedding_caches",
    "embeddings",
    "memory_records",
    "tools",
    "request_logs",
    "events",
    "workflows",
    "webhook_events",
    "webhook_subscriptions",
    "usage_events",
    "wallet_transactions",
    "wallets",
    "notifications",
    "messages",
    "conversations",
    "api_keys",
    "knowledge_sources",
    "documents",
    "knowledge_bases",
    "projects",
    "organizations",
    "health_metrics",
    "runtime_health_checks",
    "email_verification_tokens",
    "provider_connections",
    "onboarding_states",
    "processed_webhook_events",
    "refresh_tokens",
    "pricing_rules",
    "usage_logs",
    "budgets",
    "webhook_deliveries",
    "workflow_executions",
    "models",
    "providers",
    "sessions",
]


async def table_exists(table_name: str) -> bool:
    async with AsyncSession(engine) as session:
        result = await session.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name = :name"
            ),
            {"name": table_name},
        )
        return result.scalar() is not None


async def truncate_table(table_name: str) -> bool:
    async with AsyncSession(engine) as session:
        try:
            await session.execute(text(f'TRUNCATE TABLE "{table_name}" CASCADE'))
            await session.commit()
            print(f"  truncated: {table_name}")
            return True
        except Exception as exc:
            print(f"  skipped ({table_name}): {type(exc).__name__}: {exc}")
            try:
                await session.rollback()
            except Exception:
                pass
            return False


async def truncate_all_tables():
    exists = [t for t in TRUNCATE_ORDER if await table_exists(t)]

    if not exists:
        print("  No tables found to truncate.")
        return

    print(f"  Truncating {len(exists)} tables...")
    for t in exists:
        await truncate_table(t)


async def delete_all_users():
    async with AsyncSession(engine) as session:
        try:
            result = await session.execute(text("DELETE FROM users"))
            await session.commit()
            print(f"  Deleted {result.rowcount} users")
        except Exception as exc:
            print(f"  Error deleting users: {type(exc).__name__}: {exc}")
            try:
                await session.rollback()
            except Exception:
                pass


async def main():
    print("============================================")
    print("  WARNING: This will delete ALL data")
    print("  from the database (all tables).")
    print("============================================")
    print()
    print("Press Ctrl+C within 3 seconds to abort; otherwise proceeding...")

    try:
        await asyncio.sleep(3)
    except asyncio.CancelledError:
        print("\nAborted.")
        return

    print("\nProceeding...\n")

    print("Step 1: Truncating all tables...")
    await truncate_all_tables()

    print("\nStep 2: Deleting users...")
    await delete_all_users()

    print("\nDone.")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nAborted by user.")
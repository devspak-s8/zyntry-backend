import asyncio
import sys
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.core.config import settings

async def main():
    url = settings.DATABASE_URL
    if url.startswith("postgresql://") and "+asyncpg" not in url:
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    engine = create_async_engine(url, echo=False)
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with sf() as session:
        result = await session.execute(
            text("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename='budgets'")
        )
        rows = result.all()
        print("budgets table exists:", bool(rows))
        result2 = await session.execute(text("SELECT COUNT(*) FROM wallets"))
        print("wallets count:", result2.scalar())

asyncio.run(main())

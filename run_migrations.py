from __future__ import annotations

import asyncio
import sys

from app.core.config import settings
from app.core.database import engine
from app.core.logging import configure_logging


async def run() -> None:
    configure_logging()
    print(f"Running migrations against: {settings.DATABASE_URL}")
    async with engine.begin() as conn:
        from app.core.database import Base
        await conn.run_sync(Base.metadata.create_all)
    print("Migrations applied.")


def main() -> None:
    try:
        asyncio.run(run())
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

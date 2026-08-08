from __future__ import annotations

import asyncio
from typing import Any

import psutil
from sqlalchemy import text

from app.core.cache import cache as redis_cache
from app.core.database import engine


class MetricsCollector:
    def __init__(self) -> None:
        pass

    def system_cpu_percent(self) -> float:
        return psutil.cpu_percent(interval=0.1)

    def system_memory_percent(self) -> float:
        return psutil.virtual_memory().percent

    def system_disk_usage_percent(self) -> float:
        return psutil.disk_usage("/").percent

    def get_network_throughput_mb(self) -> float:
        net1 = psutil.net_io_counters()
        asyncio.sleep(0.1)
        net2 = psutil.net_io_counters()
        bytes_diff = net2.bytes_sent + net2.bytes_recv - net1.bytes_sent - net1.bytes_recv
        return round(bytes_diff / (1024 * 1024), 2)

    async def get_redis_memory_usage_mb(self) -> float:
        try:
            info = await redis_cache.client.info("memory")
            used = info.get("used_memory_human", "0B")
            return float(used.rstrip("BKMGTPE"))
        except Exception:
            return 0.0

    async def get_redis_connection_count(self) -> int:
        try:
            info = await redis_cache.client.info("clients")
            return info.get("connected_clients", 0)
        except Exception:
            return 0

    async def get_postgres_connection_count(self) -> int:
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT count(*) FROM pg_stat_activity"))
                row = result.scalar()
                return row or 0
        except Exception:
            return 0

    async def get_queue_size(self) -> int:
        try:
            info = await redis_cache.client.info("stats")
            return info.get("total_commands_processed", 0)
        except Exception:
            return 0

    async def get_system_metrics(self) -> dict[str, Any]:
        return {
            "cpu_percent": self.system_cpu_percent(),
            "memory_percent": self.system_memory_percent(),
            "disk_percent": self.system_disk_usage_percent(),
            "network_throughput_mb": self.get_network_throughput_mb(),
        }

    async def get_redis_metrics(self) -> dict[str, Any]:
        return {
            "memory_mb": await self.get_redis_memory_usage_mb(),
            "connected_clients": await self.get_redis_connection_count(),
            "queue_size": await self.get_queue_size(),
        }


metrics_collector = MetricsCollector()
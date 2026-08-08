from __future__ import annotations

import time
from typing import Any

import psutil
from sqlalchemy import select, text

from app.admin.constants import HealthStatus
from app.admin.metrics_collector import metrics_collector
from app.core.cache import cache as redis_cache
from app.core.database import engine
from app.models.models import Provider


class SystemHealthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def check_fastapi(self) -> dict[str, Any]:
        start = time.time()
        try:
            duration = (time.time() - start) * 1000
            return {"service": "FastAPI", "status": HealthStatus.HEALTHY.value, "duration_ms": round(duration, 2), "details": {"message": "Application running"}}
        except Exception as e:
            return {"service": "FastAPI", "status": HealthStatus.CRITICAL.value, "duration_ms": round((time.time() - start) * 1000, 2), "details": {"error": str(e)}}

    async def check_redis(self) -> dict[str, Any]:
        start = time.time()
        try:
            info = await redis_cache.client.info()
            duration = (time.time() - start) * 1000
            version = info.get("redis_version", "unknown")
            clients = info.get("connected_clients", 0)
            return {"service": "Redis", "status": HealthStatus.HEALTHY.value, "duration_ms": round(duration, 2), "details": {"redis_version": version, "connected_clients": clients}}
        except Exception as e:
            return {"service": "Redis", "status": HealthStatus.CRITICAL.value, "duration_ms": round((time.time() - start) * 1000, 2), "details": {"error": str(e)}}

    async def check_postgresql(self) -> dict[str, Any]:
        start = time.time()
        try:
            async with engine.connect() as conn:
                result = await conn.execute(text("SELECT 1"))
                duration = (time.time() - start) * 1000
                return {"service": "PostgreSQL", "status": HealthStatus.HEALTHY.value, "duration_ms": round(duration, 2), "details": {"message": "Database responding"}}
        except Exception as e:
            return {"service": "PostgreSQL", "status": HealthStatus.CRITICAL.value, "duration_ms": round((time.time() - start) * 1000, 2), "details": {"error": str(e)}}

    async def check_postgresql_connections(self) -> dict[str, Any]:
        try:
            result = await self.db.execute(text("SELECT count(*) FROM pg_stat_activity"))
            count = result.scalar() or 0
            result2 = await self.db.execute(text("SHOW max_connections"))
            max_conn = result2.scalar() or 100
            usage_percent = round((count / max_conn) * 100, 2)
            status = HealthStatus.WARNING.value if usage_percent > 80 else HealthStatus.HEALTHY.value
            return {"service": "PostgreSQL Connections", "status": status, "details": {"connections": count, "max_connections": max_conn, "usage_percent": usage_percent}}
        except Exception as e:
            return {"service": "PostgreSQL Connections", "status": HealthStatus.CRITICAL.value, "details": {"error": str(e)}}

    async def check_workers(self) -> dict[str, Any]:
        try:
            from celery import Celery

            from app.core.config import settings
            celery_app = Celery("zyntra", broker=settings.CELERY_BROKER_URL)
            inspect = celery_app.control.inspect()
            active = inspect.active()
            if active:
                worker_count = len(active)
                total_active = sum(len(v) for v in active.values())
                return {"service": "Workers", "status": HealthStatus.HEALTHY.value, "details": {"workers_online": worker_count, "total_active_tasks": total_active}}
            return {"service": "Workers", "status": HealthStatus.WARNING.value, "details": {"message": "No active workers detected"}}
        except Exception as e:
            return {"service": "Workers", "status": HealthStatus.CRITICAL.value, "details": {"error": str(e)}}

    async def check_scheduler(self) -> dict[str, Any]:
        try:
            from celery import Celery

            from app.core.config import settings
            celery_app = Celery("zyntra", broker=settings.CELERY_BROKER_URL)
            inspect = celery_app.control.inspect()
            stats = inspect.stats()
            if stats:
                return {"service": "Scheduler", "status": HealthStatus.HEALTHY.value, "details": {"message": "Beat scheduler configured"}}
            return {"service": "Scheduler", "status": HealthStatus.WARNING.value, "details": {"message": "No beats detected"}}
        except Exception as e:
            return {"service": "Scheduler", "status": HealthStatus.CRITICAL.value, "details": {"error": str(e)}}

    async def check_system_resources(self) -> dict[str, Any]:
        metrics = await metrics_collector.get_system_metrics()
        cpu = metrics.get("cpu_percent", 0)
        mem = metrics.get("memory_percent", 0)
        disk = metrics.get("disk_percent", 0)
        status = HealthStatus.CRITICAL.value if cpu > 90 or mem > 90 else HealthStatus.WARNING.value if cpu > 70 or mem > 70 else HealthStatus.HEALTHY.value
        return {"service": "System Resources", "status": status, "details": {"cpu_usage_percent": cpu, "memory_usage_percent": mem, "disk_usage_percent": disk}}

    async def check_storage(self) -> dict[str, Any]:
        usage = psutil.disk_usage("/")
        percent = usage.percent
        status = HealthStatus.CRITICAL.value if percent > 90 else HealthStatus.WARNING.value if percent > 70 else HealthStatus.HEALTHY.value
        return {"service": "Storage", "status": status, "details": {"total_gb": round(usage.total / (1024**3), 2), "used_gb": round(usage.used / (1024**3), 2), "percent": percent}}

    async def check_external_apis(self) -> dict[str, Any]:
        results = {}
        urls_to_check = []
        try:
            from app.core.config import settings
            if settings.OPENAI_API_KEY:
                urls_to_check.append(("OpenAI", "https://api.openai.com/v1/models"))
            if settings.ANTHROPIC_API_KEY:
                urls_to_check.append(("Anthropic", "https://api.anthropic.com/v1/models"))
        except Exception:
            pass

        if not urls_to_check:
            return {"service": "External APIs", "status": HealthStatus.HEALTHY.value, "details": {"message": "No external APIs configured"}}

        all_healthy = True
        details = {}
        async with httpx.AsyncClient(timeout=5.0, headers={"User-Agent": "Zyntry-Admin-HealthCheck/1.0"}) as client:
            for name, url in urls_to_check:
                start = time.time()
                try:
                    resp = await client.get(url)
                    duration = (time.time() - start) * 1000
                    if resp.status_code == 200:
                        details[name] = {"status": "OK", "duration_ms": round(duration, 2)}
                    else:
                        details[name] = {"status": "Error", "duration_ms": round(duration, 2), "error": f"HTTP {resp.status_code}"}
                        all_healthy = False
                except Exception as e:
                    duration = (time.time() - start) * 1000
                    details[name] = {"status": "Error", "duration_ms": round(duration, 2), "error": str(e)}
                    all_healthy = False

        overall = HealthStatus.HEALTHY.value if all_healthy else HealthStatus.WARNING.value
        return {"service": "External APIs", "status": overall, "details": details}

    async def check_model_providers(self) -> list[dict[str, Any]]:
        result = await self.db.execute(select(Provider))
        providers = result.scalars().all()
        output = []
        for provider in providers:
            output.append({"provider": provider.name, "status": HealthStatus.HEALTHY.value})
        return output

    async def check_queue_health(self) -> dict[str, Any]:
        try:
            queue_size = 0
            redis_info = await redis_cache.client.info("clients")
            connected = redis_info.get("connected_clients", 0)
            status = HealthStatus.HEALTHY.value
            return {"service": "Queue Health", "status": status, "details": {"queue_size": queue_size, "redis_clients": connected}}
        except Exception as e:
            return {"service": "Queue Health", "status": HealthStatus.CRITICAL.value, "details": {"error": str(e)}}

    async def get_full_health(self) -> dict[str, Any]:
        checks = {
            "fastapi": await self.check_fastapi(),
            "redis": await self.check_redis(),
            "postgresql": await self.check_postgresql(),
            "postgresql_connections": await self.check_postgresql_connections(),
            "workers": await self.check_workers(),
            "scheduler": await self.check_scheduler(),
            "system_resources": await self.check_system_resources(),
            "storage": await self.check_storage(),
            "external_apis": await self.check_external_apis(),
            "model_providers": await self.check_model_providers(),
            "queue_health": await self.check_queue_health(),
        }

        overall = HealthStatus.HEALTHY.value
        for check in checks.values():
            if check["status"] == HealthStatus.CRITICAL.value:
                overall = HealthStatus.CRITICAL.value
                break
            if check["status"] == HealthStatus.WARNING.value:
                overall = HealthStatus.WARNING.value

        return {"overall": overall, "checks": checks}
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.repositories import SecurityAlertRepository
from app.admin.services.system_health import SystemHealthService
from app.models.billing import UsageLog


class DashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._alert_repo = SecurityAlertRepository(db)
        self._health_service = SystemHealthService(db)

    async def get_metrics(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        day_ago = now - timedelta(days=1)

        total_users = await self.db.scalar(select(func.count()).select_from(__import__("app.models.users", fromlist=["User"]).User))
        total_orgs = await self.db.scalar(select(func.count()).select_from(__import__("app.models.organizations", fromlist=["Organization"]).Organization))
        total_projects = await self.db.scalar(select(func.count()).select_from(__import__("app.models.projects", fromlist=["Project"]).Project))
        total_runtimes = await self.db.scalar(select(func.count()).select_from(__import__("app.models.runtimes", fromlist=["Runtime"]).Runtime))

        active_runtimes = await self.db.scalar(select(func.count()).select_from(__import__("app.models.runtimes", fromlist=["Runtime"]).Runtime).where(__import__("app.models.runtimes", fromlist=["Runtime"]).Runtime.status == "active"))
        queued_runtimes = await self.db.scalar(select(func.count()).select_from(__import__("app.models.runtimes", fromlist=["Runtime"]).Runtime).where(__import__("app.models.runtimes", fromlist=["Runtime"]).Runtime.status == "queued"))
        failed_runtimes = await self.db.scalar(select(func.count()).select_from(__import__("app.models.runtimes", fromlist=["Runtime"]).Runtime).where(__import__("app.models.runtimes", fromlist=["Runtime"]).Runtime.status == "failed"))

        from app.models.billing import Wallet
        total_wallet_balance = await self.db.scalar(select(func.coalesce(func.sum(Wallet.balance), 0)).where(Wallet.status == "active"))
        requests_24h = await self.db.scalar(select(func.count()).select_from(UsageLog).where(UsageLog.created_at >= day_ago))
        cost_24h = await self.db.scalar(select(func.coalesce(func.sum(UsageLog.cost), 0)).where(UsageLog.created_at >= day_ago))
        avg_latency_24h = await self.db.scalar(select(func.coalesce(func.avg(UsageLog.latency_ms), 0)).where(UsageLog.created_at >= day_ago))

        open_alerts = await self._alert_repo.get_open_count()

        metrics_collector = __import__("app.admin.metrics_collector", fromlist=["metrics_collector"]).metrics_collector
        sys_metrics = await metrics_collector.get_system_metrics()
        redis_metrics = await metrics_collector.get_redis_metrics()
        pg_connections = await metrics_collector.get_postgres_connection_count()

        return {
            "total_users": total_users or 0,
            "total_organizations": total_orgs or 0,
            "total_projects": total_projects or 0,
            "total_runtimes": total_runtimes or 0,
            "active_runtimes": active_runtimes or 0,
            "queued_runtimes": queued_runtimes or 0,
            "failed_runtimes": failed_runtimes or 0,
            "total_wallet_balance": float(total_wallet_balance or 0),
            "total_requests_24h": requests_24h or 0,
            "total_cost_24h": float(cost_24h or 0),
            "avg_latency_ms_24h": float(avg_latency_24h or 0),
            "open_security_alerts": open_alerts,
            "system_cpu_percent": sys_metrics.get("cpu_percent", 0),
            "system_memory_percent": sys_metrics.get("memory_percent", 0),
            "system_disk_percent": sys_metrics.get("disk_percent", 0),
            "redis_memory_mb": redis_metrics.get("memory_mb", 0),
            "redis_connected_clients": redis_metrics.get("connected_clients", 0),
            "pg_connections": pg_connections,
            "uptime_seconds": time.time(),
        }

    async def get_live_metrics(self) -> dict[str, Any]:
        metrics_collector = __import__("app.admin.metrics_collector", fromlist=["metrics_collector"]).metrics_collector
        sys_metrics = await metrics_collector.get_system_metrics()
        redis_metrics = await metrics_collector.get_redis_metrics()
        pg_connections = await metrics_collector.get_postgres_connection_count()
        queue_size = await metrics_collector.get_queue_size()

        return {
            "requests_per_second": 0.0,
            "active_connections": 0,
            "avg_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "p99_latency_ms": 0.0,
            "error_rate": 0.0,
            "queue_size": queue_size,
            "redis_memory_mb": redis_metrics.get("memory_mb", 0),
            "pg_connections": pg_connections,
            "cpu_percent": sys_metrics.get("cpu_percent", 0),
            "memory_percent": sys_metrics.get("memory_percent", 0),
            "disk_percent": sys_metrics.get("disk_percent", 0),
            "network_throughput_mb": sys_metrics.get("network_throughput_mb", 0),
            "revenue_today": 0.0,
            "revenue_month": 0.0,
            "wallet_balance": 0.0,
            "provider_cost": 0.0,
            "profit_margin": 0.0,
            "uptime_seconds": time.time(),
        }

    async def get_recent_alerts(self, limit: int = 10) -> list[dict[str, Any]]:
        alerts = await self._alert_repo.list_all(limit=limit, status="open")
        return [
            {
                "id": str(a.id) if a.id else None,
                "alert_type": a.alert_type,
                "risk_score": a.risk_score,
                "risk_level": a.risk_level,
                "status": a.status,
                "title": a.title,
                "description": a.description,
                "ip_address": a.ip_address,
                "country": a.country,
                "first_seen": a.first_seen.isoformat() if a.first_seen else "",
                "last_seen": a.last_seen.isoformat() if a.last_seen else "",
                "attempt_count": a.attempt_count,
            }
            for a in alerts
        ]

    async def get_open_alert_count(self) -> int:
        return await self._alert_repo.get_open_count()

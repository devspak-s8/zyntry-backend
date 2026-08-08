from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram

ACTIVE_ADMIN_CONNECTIONS = Gauge(
    "zyntra_admin_active_ws_connections",
    "Number of active admin WebSocket connections",
)

ADMIN_API_REQUESTS = Counter(
    "zyntra_admin_api_requests_total",
    "Total number of admin API requests",
    ["method", "path"],
)

ADMIN_API_LATENCY = Histogram(
    "zyntra_admin_api_latency_seconds",
    "Admin API request latency in seconds",
    ["method", "path"],
)

SECURITY_ALERTS_TOTAL = Counter(
    "zyntra_security_alerts_total",
    "Total number of security alerts generated",
    ["alert_type", "risk_level"],
)

PLATFORM_LATENCY = Histogram(
    "zyntra_platform_latency_ms",
    "Platform request latency in milliseconds",
    ["provider", "model"],
)

PLATFORM_ERROR_RATE = Gauge(
    "zyntra_platform_error_rate",
    "Platform error rate percentage",
    ["provider", "model"],
)

PLATFORM_RPS = Gauge(
    "zyntra_platform_requests_per_second",
    "Platform requests per second",
)

WORKER_COUNT = Gauge(
    "zyntra_workers_active",
    "Number of active workers",
)

SYSTEM_CPU = Gauge(
    "zyntra_system_cpu_percent",
    "System CPU usage percentage",
)

SYSTEM_MEMORY = Gauge(
    "zyntra_system_memory_percent",
    "System memory usage percentage",
)

SYSTEM_DISK = Gauge(
    "zyntra_system_disk_percent",
    "System disk usage percentage",
)

REDIS_MEMORY = Gauge(
    "zyntra_redis_memory_mb",
    "Redis memory usage in MB",
)

POSTGRES_CONNECTIONS = Gauge(
    "zyntra_postgres_connections",
    "Number of active PostgreSQL connections",
)

QUEUE_SIZE = Gauge(
    "zyntra_queue_size",
    "Current queue size",
)

WALLET_BALANCE_TOTAL = Gauge(
    "zyntra_wallet_balance_total",
    "Total wallet balance across platform",
)

PROVIDER_COST_TOTAL = Gauge(
    "zyntra_provider_cost_total",
    "Total provider cost",
)


def record_admin_request(method: str, path: str, status_code: int, duration: float) -> None:
    ADMIN_API_REQUESTS.labels(method=method, path=path).inc()
    ADMIN_API_LATENCY.labels(method=method, path=path).observe(duration)


def record_security_alert(alert_type: str, risk_level: str) -> None:
    SECURITY_ALERTS_TOTAL.labels(alert_type=alert_type, risk_level=risk_level).inc()


def update_system_gauges(cpu: float, memory: float, disk: float, redis_memory: float, pg_connections: int, queue_size: int, wallet_balance: float, provider_cost: float) -> None:
    SYSTEM_CPU.set(cpu)
    SYSTEM_MEMORY.set(memory)
    SYSTEM_DISK.set(disk)
    REDIS_MEMORY.set(redis_memory)
    POSTGRES_CONNECTIONS.set(pg_connections)
    QUEUE_SIZE.set(queue_size)
    WALLET_BALANCE_TOTAL.set(wallet_balance)
    PROVIDER_COST_TOTAL.set(provider_cost)


def get_prometheus_registry():
    from prometheus_client import Registry
    return Registry()


async def generate_prometheus_metrics() -> str:
    from prometheus_client import generate_latest as _generate_latest
    return _generate_latest().decode("utf-8")
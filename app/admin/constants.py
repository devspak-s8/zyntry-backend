from __future__ import annotations

from enum import Enum


class AdminRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    SECURITY_ANALYST = "security_analyst"
    BILLING_ADMIN = "billing_admin"
    RUNTIME_OPERATOR = "runtime_operator"
    VIEWER = "viewer"


class Permission(str, Enum):
    SUPER_ADMIN = "super_admin"
    DASHBOARD_READ = "dashboard.read"
    DASHBOARD_LIVE = "dashboard.live"
    REQUESTS_READ = "requests.read"
    SECURITY_READ = "security.read"
    SECURITY_ACTIONS = "security.actions"
    IP_INTELLIGENCE_READ = "ip_intelligence.read"
    IP_INTELLIGENCE_WRITE = "ip_intelligence.write"
    FINGERPRINTS_READ = "fingerprints.read"
    RUNTIMES_READ = "runtimes.read"
    RUNTIMES_WRITE = "runtimes.write"
    MODELS_READ = "models.read"
    MODELS_WRITE = "models.write"
    BILLING_READ = "billing.read"
    BILLING_WRITE = "billing.write"
    USAGE_READ = "usage.read"
    EVENTS_READ = "events.read"
    EVENTS_REPLAY = "events.replay"
    HEALTH_READ = "health.read"
    AUDIT_READ = "audit.read"
    FEATURE_FLAGS_READ = "feature_flags.read"
    FEATURE_FLAGS_WRITE = "feature_flags.write"
    NOTIFICATIONS_READ = "notifications.read"
    NOTIFICATIONS_WRITE = "notifications.write"
    AUTH_LOGIN = "auth.login"
    AUTH_LOGOUT = "auth.logout"
    AUTH_MFA = "auth.mfa"


ROLE_PERMISSIONS: dict[AdminRole, set[Permission]] = {
    AdminRole.SUPER_ADMIN: set(Permission),
    AdminRole.SECURITY_ANALYST: {
        Permission.DASHBOARD_READ,
        Permission.DASHBOARD_LIVE,
        Permission.REQUESTS_READ,
        Permission.SECURITY_READ,
        Permission.SECURITY_ACTIONS,
        Permission.IP_INTELLIGENCE_READ,
        Permission.FINGERPRINTS_READ,
        Permission.EVENTS_READ,
        Permission.EVENTS_REPLAY,
        Permission.AUDIT_READ,
        Permission.NOTIFICATIONS_READ,
        Permission.AUTH_LOGIN,
        Permission.AUTH_LOGOUT,
        Permission.AUTH_MFA,
    },
    AdminRole.BILLING_ADMIN: {
        Permission.DASHBOARD_READ,
        Permission.BILLING_READ,
        Permission.BILLING_WRITE,
        Permission.USAGE_READ,
        Permission.NOTIFICATIONS_READ,
        Permission.AUDIT_READ,
        Permission.AUTH_LOGIN,
        Permission.AUTH_LOGOUT,
        Permission.AUTH_MFA,
    },
    AdminRole.RUNTIME_OPERATOR: {
        Permission.DASHBOARD_READ,
        Permission.DASHBOARD_LIVE,
        Permission.RUNTIMES_READ,
        Permission.RUNTIMES_WRITE,
        Permission.MODELS_READ,
        Permission.MODELS_WRITE,
        Permission.EVENTS_READ,
        Permission.HEALTH_READ,
        Permission.NOTIFICATIONS_READ,
        Permission.AUDIT_READ,
        Permission.AUTH_LOGIN,
        Permission.AUTH_LOGOUT,
        Permission.AUTH_MFA,
    },
    AdminRole.VIEWER: {
        Permission.DASHBOARD_READ,
        Permission.REQUESTS_READ,
        Permission.SECURITY_READ,
        Permission.IP_INTELLIGENCE_READ,
        Permission.FINGERPRINTS_READ,
        Permission.RUNTIMES_READ,
        Permission.MODELS_READ,
        Permission.BILLING_READ,
        Permission.USAGE_READ,
        Permission.EVENTS_READ,
        Permission.HEALTH_READ,
        Permission.AUDIT_READ,
        Permission.NOTIFICATIONS_READ,
        Permission.AUTH_LOGIN,
        Permission.AUTH_LOGOUT,
        Permission.AUTH_MFA,
    },
}


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


RISK_SCORE_THRESHOLDS = {
    RiskLevel.LOW: (0, 30),
    RiskLevel.MEDIUM: (31, 50),
    RiskLevel.HIGH: (51, 75),
    RiskLevel.CRITICAL: (76, 100),
}


def risk_level_from_score(score: int) -> RiskLevel:
    for level, (low, high) in RISK_SCORE_THRESHOLDS.items():
        if low <= score <= high:
            return level
    return RiskLevel.LOW


class IPBanType(str, Enum):
    TEMPORARY = "temporary"
    PERMANENT = "permanent"


class IPActionType(str, Enum):
    BAN = "ban"
    WHITELIST = "whitelist"
    BLACKLIST = "blacklist"
    RATE_LIMIT = "rate_limit"


class AlertStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class AlertActionType(str, Enum):
    BLOCK_IP = "block_ip"
    BLOCK_FINGERPRINT = "block_fingerprint"
    SUSPEND_USER = "suspend_user"
    DISABLE_API_KEY = "disable_api_key"
    FREEZE_WALLET = "freeze_wallet"
    LOCK_ORGANIZATION = "lock_organization"
    REQUIRE_MFA = "require_mfa"
    CLEAR_ALERT = "clear_alert"


class FeatureScope(str, Enum):
    PROVIDER = "provider"
    TOOL = "tool"
    KNOWLEDGE = "knowledge"
    RUNTIME = "runtime"
    BILLING = "billing"
    ROUTING = "routing"
    EXPERIMENTAL = "experimental"


class FeatureFlagType(str, Enum):
    TOGGLE = "toggle"
    PERCENTAGE = "percentage"
    GRADUAL = "gradual"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


class NotificationProviderType(str, Enum):
    EMAIL = "email"
    SLACK = "slack"
    DISCORD = "discord"
    TELEGRAM = "telegram"
    WEBHOOK = "webhook"


class NotificationEventType(str, Enum):
    CRITICAL_ERROR = "critical_error"
    PROVIDER_FAILURE = "provider_failure"
    REDIS_DOWN = "redis_down"
    DATABASE_DOWN = "database_down"
    MASSIVE_TRAFFIC_SPIKE = "massive_traffic_spike"
    SECURITY_ATTACK = "security_attack"
    LOW_WALLET_BALANCE = "low_wallet_balance"
    PAYMENT_FAILURE = "payment_failure"
    WEBHOOK_FAILURE = "webhook_failure"
    QUEUE_OVERFLOW = "queue_overflow"
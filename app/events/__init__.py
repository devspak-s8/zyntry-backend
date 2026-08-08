from __future__ import annotations

from enum import Enum
from typing import Any


class NotificationChannel(str, Enum):
    EMAIL = "email"
    WEBHOOK = "webhook"
    REALTIME = "realtime"
    SLACK = "slack"
    DISCORD = "discord"
    SMS = "sms"


class NotificationPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class NotificationEvent:
    def __init__(
        self,
        event_type: str,
        recipient: str | list[str],
        data: dict[str, Any],
        channels: list[NotificationChannel] | None = None,
        priority: NotificationPriority = NotificationPriority.NORMAL,
        category: str = "general",
        sender_name: str | None = None,
        sender_email: str | None = None,
        reply_to: str | None = None,
    ) -> None:
        self.event_type = event_type
        self.recipient = recipient
        self.data = data
        self.channels = channels or [NotificationChannel.EMAIL]
        self.priority = priority
        self.category = category
        self.sender_name = sender_name
        self.sender_email = sender_email
        self.reply_to = reply_to


class EventType:
    AUTH_WELCOME = "auth.welcome"
    AUTH_VERIFY_EMAIL = "auth.verify_email"
    AUTH_EMAIL_VERIFIED = "auth.email_verified"
    AUTH_LOGIN_CODE = "auth.login_code"
    AUTH_MAGIC_LINK = "auth.magic_link"
    AUTH_EMAIL_CHANGED = "auth.email_changed"
    AUTH_ACCOUNT_DELETION = "auth.account_deletion"
    AUTH_PASSWORD_RESET = "auth.password_reset"
    AUTH_PASSWORD_CHANGED = "auth.password_changed"

    PROJECT_CREATED = "project.created"

    API_KEY_CREATED = "api_key.created"
    API_KEY_ROTATED = "api_key.rotated"
    API_KEY_REVOKED = "api_key.revoked"
    API_KEY_EXPIRED = "api_key.expired"
    API_KEY_ABUSE = "api_key.abuse"

    PROVIDER_CONNECTED = "provider.connected"
    PROVIDER_DISCONNECTED = "provider.disconnected"
    PROVIDER_TOKEN_EXPIRED = "provider.token_expired"
    PROVIDER_RECONNECT_REQUIRED = "provider.reconnect_required"

    RUNTIME_BUILD_STARTED = "runtime.build_started"
    RUNTIME_BUILD_COMPLETED = "runtime.build_completed"
    RUNTIME_BUILD_FAILED = "runtime.build_failed"
    RUNTIME_REBUILD_STARTED = "runtime.rebuild_started"
    RUNTIME_REBUILD_COMPLETED = "runtime.rebuild_completed"
    RUNTIME_PAUSED = "runtime.paused"
    RUNTIME_RESUMED = "runtime.resumed"
    RUNTIME_UNHEALTHY = "runtime.unhealthy"
    RUNTIME_RECOVERED = "runtime.recovered"
    RUNTIME_DELETED = "runtime.deleted"

    SOURCE_CONNECTED = "source.connected"
    SOURCE_DISCONNECTED = "source.disconnected"
    SOURCE_REAUTH_REQUIRED = "source.reauth_required"
    SOURCE_SYNC_STARTED = "source.sync_started"
    SOURCE_SYNC_COMPLETED = "source.sync_completed"
    SOURCE_SYNC_FAILED = "source.sync_failed"

    BILLING_CREDITS_PURCHASED = "billing.credits_purchased"
    BILLING_CREDITS_LOW = "billing.credits_low"
    BILLING_CREDITS_EXHAUSTED = "billing.credits_exhausted"
    BILLING_PAYMENT_SUCCESS = "billing.payment_success"
    BILLING_PAYMENT_FAILED = "billing.payment_failed"
    BILLING_SUBSCRIPTION_CREATED = "billing.subscription_created"
    BILLING_SUBSCRIPTION_RENEWED = "billing.subscription_renewed"
    BILLING_SUBSCRIPTION_CANCELED = "billing.subscription_canceled"
    BILLING_REFUND_PROCESSED = "billing.refund_processed"
    BILLING_INVOICE_AVAILABLE = "billing.invoice_available"
    BILLING_WALLET_SUCCESS = "billing.wallet_success"
    BILLING_WALLET_FAILED = "billing.wallet_failed"
    BILLING_LOW_BALANCE = "billing.low_balance"

    DEPLOYMENT_STARTED = "deployment.started"
    DEPLOYMENT_SUCCEEDED = "deployment.succeeded"
    DEPLOYMENT_FAILED = "deployment.failed"
    DEPLOYMENT_ROLLED_BACK = "deployment.rolled_back"

    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_WAITING_APPROVAL = "workflow.waiting_approval"
    WORKFLOW_DANGEROUS_ACTION = "workflow.dangerous_action"
    WORKFLOW_SCHEDULED_EXECUTED = "workflow.scheduled_executed"
    WORKFLOW_SCHEDULED_FAILED = "workflow.scheduled_failed"

    SECURITY_NEW_LOGIN = "security.new_login"
    SECURITY_NEW_DEVICE = "security.new_device"
    SECURITY_NEW_COUNTRY = "security.new_country"
    SECURITY_SUSPICIOUS_LOGIN = "security.suspicious_login"
    SECURITY_ALERT = "security.alert"
    SECURITY_MFA_ENABLED = "security.mfa_enabled"
    SECURITY_MFA_DISABLED = "security.mfa_disabled"
    SECURITY_RECOVERY_CODES = "security.recovery_codes"
    SECURITY_OAUTH_PERMISSIONS = "security.oauth_permissions"

    SYSTEM_NEW_USER = "system.new_user"
    SYSTEM_NEW_ORGANIZATION = "system.new_organization"
    SYSTEM_LARGE_PAYMENT = "system.large_payment"
    SYSTEM_RUNTIME_FAILING = "system.runtime_failing"
    SYSTEM_HIGH_USAGE = "system.high_usage"
    SYSTEM_ABUSE = "system.abuse"
    SYSTEM_SUPPORT_CREATED = "system.support_created"
    SYSTEM_SUPPORT_UPDATED = "system.support_updated"
    SYSTEM_SUPPORT_RESOLVED = "system.support_resolved"

    NOTIFICATION_WEEKLY_USAGE = "notification.weekly_usage"
    NOTIFICATION_INCIDENT = "notification.incident"
    NOTIFICATION_SERVICE_RESTORED = "notification.service_restored"
    NOTIFICATION_MAINTENANCE = "notification.maintenance"
    NOTIFICATION_STATUS_UPDATE = "notification.status_update"
    NOTIFICATION_NEW_FEATURE = "notification.new_feature"
    NOTIFICATION_FIX = "notification.fix"

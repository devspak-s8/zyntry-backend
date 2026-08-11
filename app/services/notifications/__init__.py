from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.events import NotificationChannel, NotificationEvent

logger = logging.getLogger(__name__)

_SENDER_MAP: dict[str, tuple[str, str]] = {
    "security": ("Zyntry Security", "security@zyntry.space"),
    "billing": ("Zyntry Billing", "billing@zyntry.space"),
    "support": ("Zyntry Support", "support@zyntry.space"),
    "status": ("Zyntry Status", "status@zyntry.space"),
    "default": ("Zyntry", "noreply@zyntry.space"),
}

_EMAIL_TEMPLATE_MAP: dict[str, str] = {
    "auth.welcome": "welcome",
    "auth.verify_email": "verify_email",
    "auth.email_verified": "email_verified",
    "auth.password_reset": "password_reset",
    "auth.password_changed": "password_changed",
    "project.created": "project_created",
    "auth.login_code": "login_verification_code",
    "auth.magic_link": "magic_login_link",
    "auth.email_changed": "email_changed",
    "auth.account_deletion": "account_deletion_confirmation",
    "api_key.abuse": "api_abuse_detected",
    "api_key.created": "api_key_created",
    "api_key.rotated": "api_key_rotated",
    "api_key.revoked": "api_key_revoked",
    "api_key.expired": "api_key_expired",
    "provider.connected": "provider_connected",
    "provider.disconnected": "provider_disconnected",
    "provider.token_expired": "provider_token_expired",
    "provider.reconnect_required": "provider_reconnect_required",
    "runtime.build_started": "runtime_build_started",
    "runtime.build_completed": "runtime_ready",
    "runtime.build_failed": "runtime_failed",
    "runtime.rebuild_started": "runtime_rebuild_started",
    "runtime.rebuild_completed": "runtime_rebuild_completed",
    "runtime.paused": "runtime_paused",
    "runtime.resumed": "runtime_resumed",
    "runtime.unhealthy": "runtime_unhealthy",
    "runtime.recovered": "runtime_recovered",
    "runtime.deleted": "runtime_deleted",
    "source.connected": "source_connected",
    "source.disconnected": "source_disconnected",
    "source.reauth_required": "source_reauth",
    "source.sync_started": "knowledge_sync_started",
    "source.sync_completed": "source_sync_finished",
    "source.sync_failed": "source_sync_failed",
    "billing.credits_purchased": "credits_purchased",
    "billing.credits_low": "credits_running_low",
    "billing.credits_exhausted": "credits_exhausted",
    "billing.wallet_success": "wallet_success",
    "billing.wallet_failed": "wallet_failed",
    "billing.low_balance": "low_balance",
    "billing.payment_success": "payment_successful",
    "billing.payment_failed": "payment_failed",
    "billing.invoice_available": "invoice_available",
    "billing.subscription_created": "subscription_created",
    "billing.subscription_renewed": "subscription_renewed",
    "billing.subscription_canceled": "subscription_canceled",
    "billing.refund_processed": "refund_processed",
    "deployment.started": "deployment_started",
    "deployment.succeeded": "deployment_succeeded",
    "deployment.failed": "deployment_failed",
    "deployment.rolled_back": "deployment_rolled_back",
    "workflow.completed": "workflow_completed",
    "workflow.failed": "workflow_failed",
    "workflow.waiting_approval": "workflow_waiting_approval",
    "workflow.dangerous_action": "dangerous_action_confirmation",
    "workflow.scheduled_executed": "scheduled_workflow_executed",
    "workflow.scheduled_failed": "scheduled_workflow_failed",
    "security.new_login": "new_login_detected",
    "security.new_device": "login_from_new_device",
    "security.new_country": "login_from_new_country",
    "security.suspicious_login": "suspicious_login",
    "security.alert": "security_alert",
    "security.mfa_enabled": "mfa_enabled",
    "security.mfa_disabled": "mfa_disabled",
    "security.recovery_codes": "recovery_codes_regenerated",
    "security.oauth_permissions": "oauth_permission_changed",
    "system.new_user": "new_user_registered",
    "system.new_organization": "new_organization_created",
    "system.large_payment": "large_payment_received",
    "system.runtime_failing": "runtime_repeatedly_failing",
    "system.high_usage": "high_infrastructure_usage_alert",
    "system.abuse": "abuse_detected",
    "system.support_created": "support_ticket_created",
    "system.support_updated": "support_updated",
    "system.support_resolved": "support_resolved",
    "notification.weekly_usage": "weekly_usage_summary",
    "notification.incident": "incident_notification",
    "notification.service_restored": "service_restored",
    "notification.maintenance": "maintenance_notice",
    "notification.status_update": "status_update",
    "notification.new_feature": "new_feature",
    "notification.fix": "fix_notification",
}


class NotificationWorker:
    def __init__(self) -> None:
        self._channels: dict[NotificationChannel, Any] = {
            NotificationChannel.EMAIL: self._send_email,
            NotificationChannel.WEBHOOK: self._send_webhook,
            NotificationChannel.REALTIME: self._send_realtime,
            NotificationChannel.SLACK: self._send_slack,
            NotificationChannel.DISCORD: self._send_discord,
        }

    async def process(self, event: NotificationEvent) -> dict[str, Any]:
        results: dict[str, Any] = {}
        for channel in event.channels:
            handler = self._channels.get(channel)
            if handler is None:
                continue
            try:
                results[channel.value] = await handler(event)
            except Exception as exc:
                results[channel.value] = {"success": False, "error": str(exc)}
        return results

    async def _send_email(self, event: NotificationEvent) -> dict[str, Any]:
        from app.emails import send_email

        category = event.category or "general"
        sender_name, sender_email = _SENDER_MAP.get(category, _SENDER_MAP["default"])
        if event.sender_name:
            sender_name = event.sender_name
        if event.sender_email:
            sender_email = event.sender_email

        reply_to = event.reply_to or (
            "support@zyntry.space" if category == "support" else None
        )

        template_name = _EMAIL_TEMPLATE_MAP.get(
            event.event_type, event.event_type.replace(".", "_")
        )
        result = await send_email(
            template_name=template_name,
            to=event.recipient,
            reply_to=reply_to,
            from_email=sender_email,
            from_name=sender_name,
            category=category,
            priority=event.priority.value,
            **event.data,
        )
        return result

    async def _send_webhook(self, event: NotificationEvent) -> dict[str, Any]:
        return {"success": True, "channel": "webhook", "event": event.event_type}

    async def _send_realtime(self, event: NotificationEvent) -> dict[str, Any]:
        return {"success": True, "channel": "realtime", "event": event.event_type}

    async def _send_slack(self, event: NotificationEvent) -> dict[str, Any]:
        return {"success": True, "channel": "slack", "event": event.event_type}

    async def _send_discord(self, event: NotificationEvent) -> dict[str, Any]:
        return {"success": True, "channel": "discord", "event": event.event_type}


notification_worker = NotificationWorker()


async def publish_notification(event: NotificationEvent) -> dict[str, Any]:
    return await notification_worker.process(event)


async def _safe_fire(coro: Any) -> None:
    try:
        result = await coro
        if isinstance(result, dict):
            failures = {
                channel: outcome
                for channel, outcome in result.items()
                if isinstance(outcome, dict) and outcome.get("success") is False
            }
            if failures:
                logger.error("Notification delivery failed: %s", failures)
    except Exception as exc:
        logger.exception("Notification task failed: %s", exc)


def enqueue_notification(event: NotificationEvent) -> None:
    asyncio.create_task(_safe_fire(notification_worker.process(event)))

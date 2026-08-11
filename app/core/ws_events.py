from __future__ import annotations


def _get_manager():
    from app.main import manager
    return manager


async def emit_to_user(user_id: str, event: str, payload: dict) -> None:
    await _get_manager().send_to_user(
        {"type": event, "payload": payload},
        user_id,
    )


async def emit_provider_updated(user_id: str, project_id: str, provider_name: str, is_active: bool) -> None:
    await emit_to_user(user_id, "provider.updated", {
        "project_id": project_id,
        "provider_name": provider_name,
        "is_active": is_active,
    })


async def emit_wallet_updated(user_id: str, wallet_id: str, balance: str, currency: str) -> None:
    await emit_to_user(user_id, "wallet.updated", {
        "wallet_id": wallet_id,
        "balance": balance,
        "currency": currency,
    })


async def emit_checkout_completed(user_id: str, checkout_id: str, status: str) -> None:
    await emit_to_user(user_id, "checkout.completed", {
        "checkout_id": checkout_id,
        "status": status,
    })


async def emit_knowledge_sync_updated(
    user_id: str,
    *,
    job_id: str,
    source_id: str,
    project_id: str,
    status: str,
    progress: int,
    current_step: str,
    error_message: str | None = None,
    stats: dict | None = None,
) -> None:
    await emit_to_user(
        user_id,
        "knowledge.sync.updated",
        {
            "job_id": job_id,
            "source_id": source_id,
            "project_id": project_id,
            "status": status,
            "progress": progress,
            "current_step": current_step,
            "error_message": error_message,
            "stats": stats or {},
        },
    )


async def emit_knowledge_sync_log(
    user_id: str,
    *,
    job_id: str,
    source_id: str,
    project_id: str,
    event: str,
    message: str,
    details: dict | None = None,
) -> None:
    await emit_to_user(
        user_id,
        "knowledge.sync.log",
        {
            "job_id": job_id,
            "source_id": source_id,
            "project_id": project_id,
            "event": event,
            "message": message,
            "details": details or {},
        },
    )


async def emit_integration_connection_updated(
    user_id: str,
    *,
    project_id: str,
    provider: str,
    purpose: str,
    oauth_connection_id: str,
    tool_id: str | None,
    source_id: str | None,
) -> None:
    await emit_to_user(
        user_id,
        "integration.connection.updated",
        {
            "project_id": project_id,
            "provider": provider,
            "purpose": purpose,
            "connected": True,
            "oauth_connection_id": oauth_connection_id,
            "tool_id": tool_id,
            "source_id": source_id,
        },
    )


async def emit_notification(user_id: str, title: str, message: str, notification_type: str = "info") -> None:
    await emit_to_user(user_id, "notification", {
        "title": title,
        "message": message,
        "type": notification_type,
    })

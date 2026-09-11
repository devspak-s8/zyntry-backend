"""Shared contracts and small helpers for the runtime invocation API.

The HTTP router should coordinate the request lifecycle, not own persistence
queries, billing calculations, and tool metadata rules.  Keeping these small
pieces here also makes them reusable by background invocations and contract
tests without importing a FastAPI route module.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any, cast

import httpx
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import safe_public_message
from app.models.chat import Conversation, Message
from app.schemas.actions import ActionRequest, ActionResponse
from app.services.security.outbound import validate_outbound_url

logger = logging.getLogger(__name__)


def insufficient_credits_detail() -> dict[str, str]:
    return {
        "error": "Insufficient credits",
        "message": "Add credits to continue.",
    }


def normalize_runtime_status(status_value: Any) -> str | None:
    if status_value is None:
        return None
    return str(status_value).strip().lower()


def is_runtime_ready(status_value: Any) -> bool:
    normalized = normalize_runtime_status(status_value)
    return normalized is None or normalized not in {"failed", "cancelled"}


async def charge_invoke_if_billable(
    billing_service: Any,
    *,
    user_id: uuid.UUID,
    amount: Decimal,
    reason: str,
    reference_id: str,
    metadata: dict[str, Any],
) -> None:
    """Do not create an invalid zero-value debit when pricing is not configured."""
    if amount <= Decimal("0"):
        return
    await billing_service.deduct_credit(
        user_id=user_id,
        amount=amount,
        reason=reason,
        reference_id=reference_id,
        metadata=metadata,
    )


def catalog_token_cost(
    candidate: Any,
    *,
    input_tokens: int,
    output_tokens: int,
) -> Decimal:
    if candidate is None:
        return Decimal("0")
    info = candidate.model_info
    input_rate = Decimal(str(info.input_price_per_1k or 0))
    output_rate = Decimal(str(info.output_price_per_1k or 0))
    cost = (
        input_rate * Decimal(input_tokens) / Decimal(1000)
        + output_rate * Decimal(output_tokens) / Decimal(1000)
    )
    if cost > 0:
        return max(cost, Decimal("0.0001"))
    return Decimal("0")


class InvokeRequest(BaseModel):
    # A project is normally inferred from the scoped API key. Keeping this
    # optional lets server-to-server clients configure only the Zyntry URL and
    # key while preserving an explicit project override for multi-project keys.
    project: str | None = None
    input: str
    runtime_id: str | None = None
    model: str | None = None
    provider: str | None = None
    max_tokens: int | None = Field(default=None, ge=1, le=131_072)
    goal: str = "balanced"
    stream: bool = False
    top_k: int = 5
    conversation_id: str | None = None
    idempotency_key: str | None = None
    json_schema: dict | None = None
    actions: list[ActionRequest] = Field(default_factory=list)
    context_sources: list[str] = Field(default_factory=list, max_length=20)
    join_on: str | None = None


class InvokeResponse(BaseModel):
    request_id: str
    response: str | None = None
    model: str
    provider: str
    latency_ms: float
    cost: float
    warnings: list[dict] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    tool_calls: list[dict] = Field(default_factory=list)
    action_results: list[ActionResponse] = Field(default_factory=list)
    source_context: dict[str, Any] | None = None
    tokens_used: int = 0
    guardrail_violations: list[str] = Field(default_factory=list)
    estimated_cost: float = 0.0
    actual_cost: float = 0.0
    remaining_balance: float | None = None
    usage: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)


async def load_recent_conversation_messages(
    db: AsyncSession,
    conversation_id: str | None,
    *,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int = 20,
) -> list[dict[str, str]]:
    """Load only conversation history owned by this project/user scope."""
    if not conversation_id:
        return []
    try:
        conversation_uuid = uuid.UUID(conversation_id)
    except (TypeError, ValueError):
        return []
    conversation = await db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_uuid,
            Conversation.project_id == project_id,
            (Conversation.user_id.is_(None) | (Conversation.user_id == user_id)),
        )
    )
    if conversation is None:
        return []
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conversation.id)
        .order_by(Message.created_at.desc())
        .limit(min(max(limit, 1), 50))
    )
    messages = list(reversed(result.scalars().all()))
    return [
        {"role": str(item.role), "content": str(item.content)}
        for item in messages
        if item.content
    ]


async def execute_tool(tool: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    """Execute a configured HTTP/webhook tool with outbound URL validation."""
    implementation = (tool.implementation or "").strip()
    if not implementation:
        return {"name": tool.name, "status": "skipped", "reason": "no_implementation"}
    if implementation.startswith(("http://", "https://")):
        url = implementation
    elif implementation.startswith("webhook://"):
        url = implementation[len("webhook://") :]
    else:
        return {
            "name": tool.name,
            "status": "skipped",
            "reason": "unsupported_implementation",
        }

    try:
        safe_url = validate_outbound_url(url)
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.post(safe_url, json=arguments)
        content_type = response.headers.get("content-type", "")
        result = response.json() if "application/json" in content_type else response.text
        return {
            "name": tool.name,
            "status": "success",
            "result": result,
            "status_code": response.status_code,
        }
    except Exception as exc:
        # Keep network/provider details in server logs, not in the client
        # response. The caller still receives a stable failure shape.
        logger.exception("Configured tool execution failed", extra={"tool": tool.name})
        return {"name": tool.name, "status": "error", "error": safe_public_message(exc, "Tool execution failed.")}


def tool_is_read_only(tool: Any) -> bool:
    """Return the persisted read-only flag for an automatic tool call."""
    raw_schema = getattr(tool, "schema", None)
    schema = cast(dict[str, Any], raw_schema) if isinstance(raw_schema, dict) else {}
    raw_custom = schema.get("_zyntry_custom")
    custom = cast(dict[str, Any], raw_custom) if isinstance(raw_custom, dict) else {}
    value = custom.get("read_only", schema.get("read_only", True))
    return value is not False

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from app.repositories import UnitOfWork
from app.schemas.runtime_assistant import (
    AssistantMessage,
    DiagnosticResult,
    OptimizationResult,
)


class RuntimeAssistantMemory:
    def __init__(self, uow: UnitOfWork, runtime_id: str) -> None:
        self.uow = uow
        self.runtime_id = runtime_id
        self._chat_history: list[AssistantMessage] = []
        self._previous_actions: list[dict[str, Any]] = []
        self._recommendations: list[dict[str, Any]] = []
        self._max_history = 100

    async def load(self) -> None:
        memory_records = await self.uow.memory_records.get_by_runtime(self.runtime_id)
        for record in memory_records:
            if record.memory_type == "chat":
                self._chat_history.append(
                    AssistantMessage(
                        role=record.key or "user",
                        content=record.value or "",
                        timestamp=record.created_at or datetime.now(timezone.utc),
                    )
                )
            elif record.memory_type == "action":
                self._previous_actions.append(
                    {"key": record.key, "value": record.value, "timestamp": record.created_at}
                )
            elif record.memory_type == "recommendation":
                self._recommendations.append(
                    {"key": record.key, "value": record.value, "timestamp": record.created_at}
                )

        self._chat_history = self._chat_history[-self._max_history :]
        self._previous_actions = self._previous_actions[-50:]
        self._recommendations = self._recommendations[-50:]

    async def save_chat_message(self, role: str, content: str) -> None:
        message = AssistantMessage(role=role, content=content)
        self._chat_history.append(message)
        if len(self._chat_history) > self._max_history:
            self._chat_history = self._chat_history[-self._max_history :]

        await self.uow.memory_records.create(
            runtime_id=uuid.UUID(self.runtime_id),
            memory_type="chat",
            key=role,
            value=content,
            metadata={"timestamp": message.timestamp.isoformat()},
        )
        await self.uow.commit()

    async def save_action(self, action_name: str, result: dict[str, Any]) -> None:
        action_record = {
            "action": action_name,
            "result": result,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._previous_actions.append(action_record)
        if len(self._previous_actions) > 50:
            self._previous_actions = self._previous_actions[-50:]

        await self.uow.memory_records.create(
            runtime_id=uuid.UUID(self.runtime_id),
            memory_type="action",
            key=action_name,
            value=str(result),
            metadata={"timestamp": action_record["timestamp"]},
        )
        await self.uow.commit()

    async def save_recommendation(
        self,
        category: str,
        title: str,
        description: str,
        actions: list[str],
    ) -> None:
        recommendation = {
            "category": category,
            "title": title,
            "description": description,
            "actions": actions,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "applied": False,
        }
        self._recommendations.append(recommendation)
        if len(self._recommendations) > 50:
            self._recommendations = self._recommendations[-50:]

        await self.uow.memory_records.create(
            runtime_id=uuid.UUID(self.runtime_id),
            memory_type="recommendation",
            key=category,
            value=title,
            metadata={
                "description": description,
                "actions": actions,
                "timestamp": recommendation["timestamp"],
                "applied": False,
            },
        )
        await self.uow.commit()

    async def mark_recommendation_applied(self, category: str, title: str) -> None:
        for rec in self._recommendations:
            if rec["category"] == category and rec["title"] == title:
                rec["applied"] = True
                break

    def get_chat_history(self, limit: int = 20) -> list[AssistantMessage]:
        return self._chat_history[-limit:]

    def get_previous_actions(self, limit: int = 10) -> list[dict[str, Any]]:
        return self._previous_actions[-limit:]

    def get_recommendations(self, applied: bool | None = None) -> list[dict[str, Any]]:
        if applied is None:
            return self._recommendations
        return [r for r in self._recommendations if r.get("applied") == applied]

    def get_context_summary(self) -> dict[str, Any]:
        recent_actions = self._previous_actions[-5:]
        recent_recommendations = [
            r for r in self._recommendations[-5:] if not r.get("applied")
        ]

        return {
            "chat_turns": len(self._chat_history),
            "recent_actions": [a.get("action") for a in recent_actions],
            "pending_recommendations": len(recent_recommendations),
            "last_interaction": self._chat_history[-1].timestamp.isoformat()
            if self._chat_history
            else None,
        }

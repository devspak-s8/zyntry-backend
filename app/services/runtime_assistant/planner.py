from __future__ import annotations

import json
import re
from typing import Any

from app.services.runtime_assistant.prompts import build_user_prompt
from app.services.runtime_assistant.configuration import parse_configuration_change
from app.services.runtime_assistant.schemas import (
    RuntimeContext,
    ToolCall,
    ToolDefinition,
    UserRole,
)


class ToolPlan:
    def __init__(
        self,
        tool_calls: list[ToolCall],
        reasoning: str,
        configuration_error: str | None = None,
    ) -> None:
        self.tool_calls = tool_calls
        self.reasoning = reasoning
        self.configuration_error = configuration_error


class RuntimeAssistantPlanner:
    def __init__(self, context: RuntimeContext, available_tools: list[ToolDefinition]) -> None:
        self.context = context
        self.available_tools = available_tools
        self.tool_map = {t.name: t for t in available_tools}

    def plan(self, user_message: str) -> ToolPlan:
        message_lower = user_message.lower()
        tool_calls: list[ToolCall] = []
        reasoning_parts: list[str] = []

        configuration_error: str | None = None
        try:
            configuration_change = parse_configuration_change(user_message)
        except ValueError as exc:
            configuration_change = None
            configuration_error = str(exc)
        if configuration_change and "update_runtime_configuration" in self.tool_map:
            reasoning_parts.append("User explicitly requested a runtime configuration change.")
            tool_calls.append(
                ToolCall(
                    id=self._generate_id(),
                    name="update_runtime_configuration",
                    arguments={"changes": configuration_change},
                )
            )
        elif re.fullmatch(r"(?:rebuild|re-index|reindex)(?:\s+(?:the\s+)?(?:runtime|embeddings?))?[!.?]*", message_lower) or any(k in message_lower for k in ["rebuild runtime", "rebuild the runtime", "rebuild embeddings", "rebuild the embeddings", "re-index", "reindex"]):
            reasoning_parts.append("User explicitly requested a runtime rebuild.")
            if "rebuild_embeddings" in self.tool_map:
                tool_calls.append(
                    ToolCall(
                        id=self._generate_id(),
                        name="rebuild_embeddings",
                        arguments={},
                    )
                )
        elif any(k in message_lower for k in ["why is my runtime slow", "slow runtime", "latency", "performance"]):
            reasoning_parts.append("User is asking about runtime performance.")
            tool_calls.extend(self._plan_slow_runtime(message_lower))

        elif any(k in message_lower for k in ["why is my runtime expensive", "expensive", "cost", "spending", "billing"]):
            reasoning_parts.append("User is asking about runtime cost.")
            tool_calls.extend(self._plan_expensive_runtime(message_lower))

        elif any(k in message_lower for k in ["inaccurate", "wrong answers", "bad results", "quality"]):
            reasoning_parts.append("User is asking about answer quality.")
            tool_calls.extend(self._plan_inaccurate_answers(message_lower))

        elif any(k in message_lower for k in ["sync failed", "sync failing", "sync error", "knowledge source"]):
            reasoning_parts.append("User is asking about sync issues.")
            tool_calls.extend(self._plan_sync_failures(message_lower))

        elif any(k in message_lower for k in [
            "are you done", "is it done", "did it apply", "was it applied",
            "has it completed", "when completed", "is it live", "did the update",
            "did the change", "was the change", "verify the change",
        ]):
            reasoning_parts.append("User is verifying whether a previous runtime change completed.")
            if "get_runtime_config" in self.tool_map:
                tool_calls.append(ToolCall(id=self._generate_id(), name="get_runtime_config", arguments={}))
            if "get_deployment_status" in self.tool_map:
                tool_calls.append(ToolCall(id=self._generate_id(), name="get_deployment_status", arguments={}))

        elif re.fullmatch(r"(?:do|did|done|check|status)\s*[?!.]*", message_lower):
            reasoning_parts.append("User is asking for a current completion check.")
            if "get_runtime_config" in self.tool_map:
                tool_calls.append(ToolCall(id=self._generate_id(), name="get_runtime_config", arguments={}))
            if "get_deployment_status" in self.tool_map:
                tool_calls.append(ToolCall(id=self._generate_id(), name="get_deployment_status", arguments={}))

        elif any(k in message_lower for k in [
            "how does automatic", "how does dynamic", "how automatic model",
            "how are models selected", "explain automatic", "explain dynamic",
            "how does routing", "how routing works",
        ]):
            reasoning_parts.append("User is asking how automatic model routing works.")
            tool_calls.extend(self._plan_dynamic_routing(message_lower))

        elif any(k in message_lower for k in ["dynamic routing", "routing", "route"]):
            reasoning_parts.append("User is asking about dynamic routing.")
            tool_calls.extend(self._plan_dynamic_routing(message_lower))

        elif any(k in message_lower for k in ["configuration", "configurationof", "configured", "settings", "temperature", "system prompt"]):
            reasoning_parts.append("User is asking about runtime configuration.")
            if "get_runtime_config" in self.tool_map:
                tool_calls.append(ToolCall(id=self._generate_id(), name="get_runtime_config", arguments={}))

        elif any(k in message_lower for k in ["what changed", "changed before", "recent change", "who changed", "configuration history", "deployment history"]):
            reasoning_parts.append("User is investigating runtime change history.")
            if "get_change_history" in self.tool_map:
                tool_calls.append(ToolCall(id=self._generate_id(), name="get_change_history", arguments={"limit": 20}))
            if "get_runtime_health" in self.tool_map:
                tool_calls.append(ToolCall(id=self._generate_id(), name="get_runtime_health", arguments={}))

        elif any(k in message_lower for k in ["summary", "overview", "status", "health"]):
            reasoning_parts.append("User is asking for runtime overview.")
            tool_calls.extend(self._plan_summary(message_lower))

        elif any(k in message_lower for k in ["cost optimization", "reduce cost", "save money", "optimize cost"]):
            reasoning_parts.append("User wants cost optimization.")
            tool_calls.extend(self._plan_cost_optimization(message_lower))

        elif any(k in message_lower for k in ["recommendation", "recommend", "suggest"]):
            reasoning_parts.append("User wants recommendations.")
            tool_calls.extend(self._plan_recommendations(message_lower))

        elif any(k in message_lower for k in ["report", "generate report"]):
            reasoning_parts.append("User wants a report.")
            tool_calls.extend(self._plan_report(message_lower))

        else:
            reasoning_parts.append("General runtime inquiry.")
            tool_calls.extend(self._plan_general(message_lower))

        reasoning = " ".join(reasoning_parts) if reasoning_parts else "Processing general request."
        if configuration_error:
            reasoning_parts.append("The requested configuration value failed validation.")
            reasoning = " ".join(reasoning_parts)
        return ToolPlan(
            tool_calls=tool_calls,
            reasoning=reasoning,
            configuration_error=configuration_error,
        )

    def classify_request(self, user_message: str) -> dict[str, Any]:
        """Return a high-level, safe execution decision for observability.

        This is intentionally a decision summary, not hidden chain-of-thought.
        It lets the console explain why a path was selected without exposing
        private model reasoning.
        """
        text = user_message.lower()
        current = any(term in text for term in ("current", "latest", "today", "now", "recent"))
        action = any(term in text for term in ("create", "send", "update", "delete", "run", "execute"))
        document = any(term in text for term in ("pdf", "document", "uploaded file", "chapter"))
        knowledge = any(term in text for term in ("what", "who", "when", "where", "how", "why", "find", "search"))
        policy = self.context.external_sources or {}
        strategy = policy.get("strategy", "internal_then_external")
        external_enabled = bool(policy.get("enabled")) and strategy != "internal_only"

        if action:
            mode = "action"
        elif knowledge or document:
            mode = "retrieval"
        else:
            mode = "direct"

        sources: list[str] = []
        for source in self.context.knowledge_sources:
            source_type = str(source.get("source_type") or source.get("provider") or "").lower()
            if source_type and (source_type in text or source_type in {"document", "documents"} and document):
                sources.append(source_type)
        if document and "documents" not in sources:
            sources.append("documents")
        external_reason = "current_information" if current else "internal_context_insufficient"
        return {
            "intent": "current_information" if current else ("document_question" if document else ("action_request" if action else "knowledge_question" if knowledge else "conversation")),
            "response_mode": mode,
            "candidate_sources": sources,
            "external_retrieval": {
                "enabled": external_enabled,
                "allowed": external_enabled and mode == "retrieval",
                "strategy": strategy,
                "reason": external_reason,
                "providers": policy.get("providers", []),
            },
            "context_selection": "relevant_sources_and_recent_execution",
        }

    def _plan_slow_runtime(self, message: str) -> list[ToolCall]:
        calls = []
        if "get_runtime_health" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_runtime_health", arguments={}))
        if "get_logs" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_logs", arguments={"limit": 20}))
        if "get_analytics" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_analytics", arguments={}))
        return calls

    def _plan_expensive_runtime(self, message: str) -> list[ToolCall]:
        calls = []
        if "run_cost_analysis" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="run_cost_analysis", arguments={}))
        if "get_billing" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_billing", arguments={}))
        if "get_providers" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_providers", arguments={}))
        return calls

    def _plan_inaccurate_answers(self, message: str) -> list[ToolCall]:
        calls = []
        if "get_knowledge_sources" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_knowledge_sources", arguments={}))
        if "get_runtime_health" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_runtime_health", arguments={}))
        if "get_logs" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_logs", arguments={"limit": 20}))
        return calls

    def _plan_sync_failures(self, message: str) -> list[ToolCall]:
        calls = []
        if "get_knowledge_sources" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_knowledge_sources", arguments={}))
        if "get_logs" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_logs", arguments={"limit": 30}))
        return calls

    def _plan_dynamic_routing(self, message: str) -> list[ToolCall]:
        calls = []
        if "get_runtime_config" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_runtime_config", arguments={}))
        # Chat produces a reviewable proposal only. Mutations are applied by a
        # separate confirmed action endpoint, never directly from prose.
        return calls

    def _plan_summary(self, message: str) -> list[ToolCall]:
        calls = []
        if "get_runtime_summary" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_runtime_summary", arguments={}))
        return calls

    def _plan_cost_optimization(self, message: str) -> list[ToolCall]:
        calls = []
        if "run_cost_analysis" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="run_cost_analysis", arguments={}))
        if "get_runtime_summary" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_runtime_summary", arguments={}))
        return calls

    def _plan_recommendations(self, message: str) -> list[ToolCall]:
        calls = []
        if "get_runtime_summary" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_runtime_summary", arguments={}))
        if "run_health_check" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="run_health_check", arguments={}))
        if "run_cost_analysis" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="run_cost_analysis", arguments={}))
        return calls

    def _plan_report(self, message: str) -> list[ToolCall]:
        calls = []
        fmt = "markdown"
        if "json" in message:
            fmt = "json"
        elif "text" in message:
            fmt = "text"
        if "generate_report" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="generate_report", arguments={"format": fmt}))
        return calls

    def _plan_general(self, message: str) -> list[ToolCall]:
        # Conversation is not a diagnostic request. Runtime data is already
        # available in the scoped control-plane snapshot, so greetings and
        # general chat must not trigger health checks on every turn.
        return []

    def _generate_id(self) -> str:
        import uuid

        return str(uuid.uuid4())[:8]

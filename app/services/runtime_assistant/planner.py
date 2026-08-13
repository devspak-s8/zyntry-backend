from __future__ import annotations

import json
import re
from typing import Any

from app.services.runtime_assistant.prompts import build_user_prompt
from app.services.runtime_assistant.schemas import (
    RuntimeContext,
    ToolCall,
    ToolDefinition,
    UserRole,
)


class ToolPlan:
    def __init__(self, tool_calls: list[ToolCall], reasoning: str) -> None:
        self.tool_calls = tool_calls
        self.reasoning = reasoning


class RuntimeAssistantPlanner:
    def __init__(self, context: RuntimeContext, available_tools: list[ToolDefinition]) -> None:
        self.context = context
        self.available_tools = available_tools
        self.tool_map = {t.name: t for t in available_tools}

    def plan(self, user_message: str) -> ToolPlan:
        message_lower = user_message.lower()
        tool_calls: list[ToolCall] = []
        reasoning_parts: list[str] = []

        if any(k in message_lower for k in ["why is my runtime slow", "slow runtime", "latency", "performance"]):
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
        return ToolPlan(tool_calls=tool_calls, reasoning=reasoning)

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
        calls = []
        if "get_runtime_summary" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="get_runtime_summary", arguments={}))
        if "run_health_check" in self.tool_map:
            calls.append(ToolCall(id=self._generate_id(), name="run_health_check", arguments={}))
        return calls

    def _generate_id(self) -> str:
        import uuid

        return str(uuid.uuid4())[:8]

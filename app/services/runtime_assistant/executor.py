from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from app.repositories import UnitOfWork
from app.services.runtime_assistant.permissions import PermissionDeniedError, check_tool_permission
from app.services.runtime_assistant.schemas import (
    ActionType,
    AssistantResponse,
    DiagnosticResult,
    OptimizationResult,
    RuntimeContext,
    RuntimeSummary,
    ToolCall,
    ToolDefinition,
    UserRole,
)
from app.services.runtime_assistant.tools import RuntimeAssistantTools


class ToolExecutionResult:
    def __init__(self, tool_call: ToolCall, success: bool) -> None:
        self.tool_call = tool_call
        self.success = success


class RuntimeAssistantExecutor:
    def __init__(
        self,
        uow: UnitOfWork,
        context: RuntimeContext,
        available_tools: list[ToolDefinition],
    ) -> None:
        self.uow = uow
        self.context = context
        self.available_tools = available_tools
        self.tool_map = {t.name: t for t in available_tools}
        self.tools_client = RuntimeAssistantTools(
            uow=uow,
            runtime_id=context.runtime_id,
            user_id=context.user_id,
            user_role=context.user_role,
            project_id=context.project_id,
        )

    async def execute_plan(self, tool_calls: list[ToolCall]) -> list[ToolExecutionResult]:
        results = []
        for call in tool_calls:
            check = check_tool_permission(
                self.context.user_role,
                call.name,
                [t.model_dump() for t in self.available_tools],
            )
            if not check.allowed:
                call.status = "permission_denied"
                call.error = check.reason
                call.timestamp = datetime.now(timezone.utc)
                call.duration_ms = 0.0
                results.append(ToolExecutionResult(tool_call=call, success=False))
                continue

            executed = await self.tools_client.execute(call)
            results.append(ToolExecutionResult(tool_call=executed, success=executed.status == "success"))
        return results

    def build_response(
        self,
        user_message: str,
        tool_results: list[ToolExecutionResult],
    ) -> AssistantResponse:
        diagnostics = self._extract_diagnostics(tool_results)
        optimizations = self._extract_optimizations(tool_results, user_message)
        summary = self._build_summary(tool_results)
        message = self._compose_message(user_message, tool_results, diagnostics, optimizations)

        return AssistantResponse(
            message=message,
            tool_calls=[r.tool_call for r in tool_results],
            diagnostics=diagnostics,
            optimizations=optimizations,
            context=self.context,
            summary=summary,
            streaming=False,
            metadata={
                "executed_tools": len(tool_results),
                "successful_tools": sum(1 for r in tool_results if r.success),
                "failed_tools": sum(1 for r in tool_results if not r.success),
            },
        )

    def _extract_diagnostics(self, results: list[ToolExecutionResult]) -> list[DiagnosticResult]:
        diagnostics: list[DiagnosticResult] = []
        for result in results:
            if not result.success or not result.tool_call.result:
                continue
            data = result.tool_call.result
            if result.tool_call.name == "run_health_check":
                if data.get("health_score", 100) < 70:
                    diagnostics.append(
                        DiagnosticResult(
                            issue="Low health score",
                            severity="warning",
                            description=f"Runtime health score is {data.get('health_score')}",
                            affected_components=["runtime"],
                            recommendations=["Review recent changes", "Check error logs"],
                            metrics={"health_score": data.get("health_score")},
                        )
                    )
                if data.get("error_count", 0) > 0:
                    diagnostics.append(
                        DiagnosticResult(
                            issue="Errors detected",
                            severity="error",
                            description=f"{data.get('error_count')} errors detected in the last 24 hours",
                            affected_components=["runtime"],
                            recommendations=["Check logs for error details"],
                            metrics={"error_count": data.get("error_count")},
                        )
                    )
            elif result.tool_call.name == "run_cost_analysis":
                total_cost = data.get("total_cost", 0)
                if total_cost and total_cost > 100:
                    diagnostics.append(
                        DiagnosticResult(
                            issue="High cost",
                            severity="warning",
                            description=f"Monthly cost is ${total_cost:.2f}",
                            affected_components=["billing"],
                            recommendations=[
                                "Review model usage",
                                "Consider cheaper alternatives",
                                "Enable dynamic routing",
                            ],
                            metrics={"total_cost": total_cost},
                        )
                    )
        return diagnostics

    def _extract_optimizations(
        self, results: list[ToolExecutionResult], user_message: str
    ) -> list[OptimizationResult]:
        optimizations: list[OptimizationResult] = []
        message_lower = user_message.lower()

        if "cost" in message_lower or "expensive" in message_lower:
            for result in results:
                if result.tool_call.name == "run_cost_analysis" and result.success:
                    data = result.tool_call.result or {}
                    total_cost = data.get("total_cost", 0)
                    if total_cost and total_cost > 50:
                        optimizations.append(
                            OptimizationResult(
                                category="cost",
                                title="Enable Dynamic Routing",
                                description="Dynamic routing can automatically select cheaper models for simple tasks.",
                                impact="high",
                                estimated_savings="20-40%",
                                actions=["enable_dynamic_routing"],
                                priority="high",
                            )
                        )

        health_data = {}
        for result in results:
            if result.tool_call.name == "run_health_check" and result.success:
                health_data = result.tool_call.result or {}
                break

        if health_data.get("health_score", 100) < 70:
            optimizations.append(
                OptimizationResult(
                    category="latency",
                    title="Optimize Runtime Performance",
                    description="Health score is below 70. Review model selection and caching.",
                    impact="high",
                    estimated_savings="30-50% latency reduction",
                    actions=["run_health_check", "clear_cache"],
                    priority="high",
                )
            )

        return optimizations

    def _build_summary(self, results: list[ToolExecutionResult]) -> RuntimeSummary | None:
        for result in results:
            if result.tool_call.name == "get_runtime_summary" and result.success:
                data = result.tool_call.result or {}
                try:
                    return RuntimeSummary(**data)
                except Exception:
                    return None
        return None

    def _compose_message(
        self,
        user_message: str,
        results: list[ToolExecutionResult],
        diagnostics: list[DiagnosticResult],
        optimizations: list[OptimizationResult],
    ) -> str:
        successful = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        result_map = {
            result.tool_call.name: result.tool_call.result
            for result in successful
            if result.tool_call.result is not None
        }
        message_lower = user_message.lower()

        if "get_change_history" in result_map:
            history = result_map["get_change_history"]
            actions = history.get("actions") or []
            deployments = history.get("deployments") or []
            if not actions and not deployments:
                return (
                    "I found no recorded configuration changes or deployments for this runtime. "
                    "I cannot truthfully identify what changed before latency increased without historical evidence."
                )
            lines = ["Recent evidence before the latency change:"]
            for action in actions[:5]:
                lines.append(
                    f"- {action.get('created_at')}: {action.get('action')} "
                    f"({action.get('status')}) by user {action.get('user_id')}."
                )
            for deployment in deployments[:5]:
                lines.append(
                    f"- {deployment.get('started_at')}: runtime stage "
                    f"{deployment.get('stage')} ({deployment.get('status')})."
                )
            lines.append(
                "This is chronological evidence; correlation with latency requires matching telemetry timestamps."
            )
            return "\n".join(lines)

        if "generate_report" in result_map:
            report = result_map["generate_report"]
            if report.get("format") == "json":
                return json.dumps(report.get("data", report), indent=2, default=str)
            return str(report.get("report", report))

        if "get_runtime_config" in result_map:
            config_result = result_map["get_runtime_config"]
            config = config_result.get("config") or {}
            routing = "enabled" if config.get("dynamic_routing_enabled") else "disabled"
            lines = [
                "Current runtime configuration:",
                f"- Provider: {config_result.get('provider') or 'automatic'}",
                f"- Model: {config_result.get('model') or 'automatic'}",
                f"- Dynamic routing: {routing}",
                f"- Temperature: {config.get('temperature', 'default')}",
                f"- Maximum tokens: {config.get('max_tokens', 'default')}",
                f"- Embedding model: {config_result.get('embedding_model') or 'default'}",
                f"- Vector store: {config_result.get('vector_store') or 'default'}",
                f"- Chunk size/overlap: {config_result.get('chunk_size')}/{config_result.get('chunk_overlap')}",
            ]
            if "enable" in message_lower and "routing" in message_lower:
                lines.extend([
                    "",
                    "Proposed change (not applied):",
                    "- Enable dynamic model routing.",
                    "- Risk: model selection, cost, and latency may change.",
                    "- Review and explicitly approve this proposal before deployment.",
                ])
            elif "disable" in message_lower and "routing" in message_lower:
                lines.extend([
                    "",
                    "Proposed change (not applied):",
                    "- Disable dynamic model routing.",
                    "- Risk: all requests may use the configured default model.",
                    "- Review and explicitly approve this proposal before deployment.",
                ])
            return "\n".join(lines)

        summary_data = result_map.get("get_runtime_summary")
        if summary_data and any(term in message_lower for term in ("three bullet", "3 bullet", "summarize")):
            return "\n".join([
                f"- Runtime is {summary_data.get('status', 'unknown')} with health {summary_data.get('health_score', 'N/A')}%.",
                f"- Requests route through {summary_data.get('provider', 'automatic')} using {summary_data.get('model', 'automatic')}.",
                f"- Knowledge contains {summary_data.get('knowledge_sources_count', 0)} sources and {summary_data.get('tools_count', 0)} connected tools.",
            ])

        parts: list[str] = []

        if diagnostics:
            parts.append(f"I found {len(diagnostics)} issue(s).\n")
            for diag in diagnostics:
                parts.append(f"• {diag.issue}: {diag.description}")
                if diag.recommendations:
                    parts.append(f"  Recommendation: {diag.recommendations[0]}")
            parts.append("")

        if optimizations:
            parts.append("Recommendations:\n")
            for opt in optimizations:
                parts.append(f"• {opt.title}")
                parts.append(f"  {opt.description}")
                if opt.estimated_savings:
                    parts.append(f"  Estimated savings: {opt.estimated_savings}")
            parts.append("")

        for result in successful:
            if result.tool_call.name == "get_runtime_summary" and result.tool_call.result:
                data = result.tool_call.result
                parts.append(f"Runtime Status: {data.get('status', 'unknown')}")
                parts.append(f"Health Score: {data.get('health_score', 'N/A')}")
                parts.append(f"Provider: {data.get('provider', 'unknown')}")
                parts.append(f"Model: {data.get('model', 'unknown')}")
                if data.get("monthly_cost"):
                    parts.append(f"Monthly Cost: ${data.get('monthly_cost'):.2f}")
                parts.append("")

        if any(term in message_lower for term in ("optimize", "improve")) and not optimizations:
            parts.extend([
                "Your runtime has no urgent optimization finding right now.",
                "Recommended next checks:",
                "- Review latency and error trends in Analytics.",
                "- Keep knowledge sources synchronized.",
                "- Use dynamic routing to balance quality, latency, and cost.",
            ])

        if not successful and not diagnostics:
            parts.append("I was unable to retrieve runtime data. Please try again.")

        return "\n".join(parts).strip()

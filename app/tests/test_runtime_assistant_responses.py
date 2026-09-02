from __future__ import annotations

from types import SimpleNamespace

from app.services.runtime_assistant.executor import RuntimeAssistantExecutor, ToolExecutionResult
from app.services.runtime_assistant.planner import RuntimeAssistantPlanner
from app.services.runtime_assistant.schemas import RuntimeContext, ToolCall, UserRole


def _executor() -> RuntimeAssistantExecutor:
    context = RuntimeContext(
        runtime_id="runtime", project_id="project", organization_id="org",
        user_id="user", user_role=UserRole.DEVELOPER,
    )
    return RuntimeAssistantExecutor(SimpleNamespace(), context, [])


def _result(name: str, value: dict) -> ToolExecutionResult:
    call = ToolCall(id="call", name=name, status="success", result=value)
    return ToolExecutionResult(call, True)


def test_configuration_question_returns_configuration() -> None:
    response = _executor().build_response(
        "What is the actual configuration of the runtime?",
        [_result("get_runtime_config", {
            "provider": "openai", "model": "gpt-4o-mini",
            "embedding_model": "text-embedding-3-small", "vector_store": "pgvector",
            "chunk_size": 800, "chunk_overlap": 100,
            "config": {"temperature": 0.3, "dynamic_routing_enabled": True},
        })],
    )
    assert "Dynamic routing: enabled" in response.message
    assert "Temperature: 0.3" in response.message


def test_three_bullet_summary_is_distinct() -> None:
    response = _executor().build_response(
        "Summarize the project status in three bullets.",
        [_result("get_runtime_summary", {
            "runtime_id": "runtime", "status": "active", "health_score": 90,
            "provider": "openai", "model": "gpt-4o-mini",
            "embedding_model": "embed", "vector_store": "pgvector",
            "knowledge_sources_count": 2, "tools_count": 3,
        })],
    )
    assert len(response.message.splitlines()) == 3
    assert "2 sources" in response.message


def test_routing_change_is_proposed_not_executed() -> None:
    response = _executor().build_response(
        "Enable dynamic routing",
        [_result("get_runtime_config", {
            "provider": "openai", "model": "gpt-4o-mini", "config": {},
            "chunk_size": 800, "chunk_overlap": 100,
        })],
    )
    assert "Proposed change (not applied)" in response.message
    assert "explicitly approve" in response.message


def test_greeting_does_not_trigger_runtime_diagnostics() -> None:
    executor = _executor()
    planner = RuntimeAssistantPlanner(executor.context, [])
    assert planner.plan("yo").tool_calls == []
    response = executor.build_response("yo", [])
    assert "I found" not in response.message
    assert "Hi!" in response.message

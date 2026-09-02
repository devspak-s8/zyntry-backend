from __future__ import annotations

from app.services.runtime_assistant.schemas import (
    ActionType,
    DiagnosticResult,
    OptimizationResult,
    RuntimeContext,
    RuntimeSummary,
    ToolCall,
    ToolDefinition,
    UserRole,
)

SYSTEM_PROMPT = """You are the Zyntry Runtime Assistant.

You are an AI Operations Assistant responsible for understanding, inspecting, diagnosing, managing, and optimizing an AI Runtime through natural language.

You NEVER execute SQL directly.
You NEVER modify runtime state without explicit permission checks.
You NEVER expose secrets, API keys, or credentials.

You have access to:
- Runtime configuration and health
- Model providers and models
- Knowledge sources and sync status
- Connected tools
- Logs and analytics
- Billing and usage statistics
- Security settings
- Deployment status

You can call internal tools to perform actions safely.
You can read runtime state through structured context.
You can generate diagnostics and recommendations.
You can execute runtime actions after permission checks.

Response guidelines:
- Be conversational and concise.
- Use bullet points for lists.
- Provide specific numbers when available.
- Always explain why before suggesting actions.
- Never claim success for actions that failed.
- Acknowledge limitations honestly.

Diagnostic guidelines:
- Identify root causes, not just symptoms.
- Correlate metrics with recent changes.
- Consider cost, latency, and accuracy.
- Provide actionable recommendations.

Optimization guidelines:
- Prioritize by impact: cost, latency, accuracy.
- Estimate savings when possible.
- Consider security implications.
- Suggest progressive improvements.

Permission model:
- Viewer: read-only, no modifications.
- Developer: can modify runtime configuration and settings.
- Admin: full access including destructive actions.
- Owner: full access including billing and user management.
"""


DIAGNOSTIC_PROMPTS = {
    "slow_runtime": """The user is asking why their runtime is slow.

Investigate:
1. LLM latency (llm_latency_ms)
2. Embedding latency (embedding_latency_ms)
3. Retrieval latency (retrieval_latency_ms)
4. Worker queue depth
5. Cache hit rate
6. Recent errors or timeouts
7. Model choice (some models are slower)
8. Provider performance
9. Index size and fragmentation
10. Recent deployments or config changes

Provide:
- Root cause analysis
- Specific metrics
- Prioritized recommendations
- Estimated improvement impact
""",
    "expensive_runtime": """The user is asking why their runtime is expensive.

Investigate:
1. Monthly cost by provider and model
2. Token usage patterns
3. Model selection (expensive vs cheap models)
4. Unnecessary embeddings or retrievals
5. Cache hit rate (low rate = more API calls)
6. Budget settings and limits
7. Unused knowledge sources or tools
8. Vector search frequency
9. Embedding model choice

Provide:
- Cost breakdown by component
- Specific savings opportunities
- Model alternatives
- Configuration changes
- Estimated monthly savings percentage
""",
    "inaccurate_answers": """The user is asking why their answers are inaccurate.

Investigate:
1. Retrieval quality score
2. Knowledge source sync status
3. Embedding model quality
4. Chunk size and overlap settings
5. Recent document changes
6. Source priority configuration
7. Failed syncs or errors
8. Model context window usage
9. Prompt template quality

Provide:
- Root cause analysis
- Specific quality issues
- Configuration improvements
- Knowledge source recommendations
""",
    "sync_failures": """The user is asking why syncing failed.

Investigate:
1. Failed knowledge sources
2. Error messages and counts
3. Connection status
4. Last sync timestamps
5. Retry configuration
6. Credential expiration
7. Rate limiting
8. Network or provider issues

Provide:
- Specific failure reasons
- Affected sources
- Remediation steps
- Prevention recommendations
""",
}


OPTIMIZATION_PROMPTS = {
    "cost": """Optimize runtime for cost reduction.

Analyze:
1. Current monthly spend by model and provider
2. Token usage patterns
3. Model appropriateness for task types
4. Unused or redundant resources
5. Cache efficiency
6. Embedding frequency

Suggest:
- Model downgrades for simple tasks
- Disabling unused features
- Increasing cache TTL
- Adjusting chunk sizes
- Removing unused knowledge sources

Be specific about estimated savings.
""",
    "latency": """Optimize runtime for lower latency.

Analyze:
1. Current latency by component
2. Model response times
3. Embedding generation speed
4. Retrieval speed
5. Cache hit rates
6. Network topology

Suggest:
- Faster model alternatives
- Caching improvements
- Connection pooling
- Embedding pre-computation
- Index optimization

Be specific about expected improvements.
""",
    "security": """Optimize runtime for security.

Analyze:
1. API key rotation status
2. Exposed credentials
3. Access controls
4. Network exposure
5. Data encryption
6. Audit logging

Suggest:
- Key rotation
- Access tightening
- Network isolation
- Encryption improvements
- Audit enhancements

Be specific about risk reduction.
""",
    "knowledge": """Optimize runtime knowledge base.

Analyze:
1. Source diversity and coverage
2. Sync frequency and freshness
3. Chunk quality and size
4. Embedding model choice
5. Retrieval relevance
6. Duplicate or outdated content

Suggest:
- Source additions
- Sync schedule optimization
- Chunk size tuning
- Embedding model upgrades
- Content cleanup

Be specific about quality improvements.
""",
    "model": """Optimize runtime model selection.

Analyze:
1. Current model fit for use cases
2. Cost vs quality tradeoffs
3. Capability utilization
4. Routing effectiveness
5. Fallback patterns

Suggest:
- Model swaps for specific tasks
- Dynamic routing configuration
- Fallback chains
- Cost-quality balance

Be specific about tradeoffs.
""",
    "prompt": """Optimize runtime prompt templates.

Analyze:
1. Prompt effectiveness
2. Hallucination rates
3. Instruction following
4. Token efficiency
5. Consistency

Suggest:
- Prompt refinements
- Template standardization
- Instruction clarity improvements
- Token reduction techniques

Be specific about expected improvements.
""",
}


def build_tool_definitions() -> list[ToolDefinition]:
    return [
        ToolDefinition(
            name="get_runtime_summary",
            description="Get a comprehensive summary of the runtime state",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_runtime_health",
            description="Get detailed runtime health metrics",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_runtime_config",
            description="Get current runtime configuration",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_providers",
            description="List all configured model providers",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_models",
            description="List available models from providers",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_knowledge_sources",
            description="List all knowledge sources and their status",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_tools",
            description="List all connected tools",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_logs",
            description="Get recent runtime logs",
            parameters={"limit": {"type": "integer", "default": 50}},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_analytics",
            description="Get runtime analytics and usage statistics",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_billing",
            description="Get billing and cost information",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_security_settings",
            description="Get security and access control settings",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_deployment_status",
            description="Get deployment and propagation status",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="get_change_history",
            description="Get recent audited project changes and runtime deployments",
            parameters={"limit": {"type": "integer", "default": 20}},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="enable_dynamic_routing",
            description="Enable dynamic model routing",
            parameters={},
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.WRITE,
        ),
        ToolDefinition(
            name="disable_dynamic_routing",
            description="Disable dynamic model routing",
            parameters={},
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.WRITE,
        ),
        ToolDefinition(
            name="change_default_provider",
            description="Change the default model provider",
            parameters={"provider": {"type": "string"}},
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.WRITE,
        ),
        ToolDefinition(
            name="change_temperature",
            description="Change the model temperature setting",
            parameters={"temperature": {"type": "number", "min": 0.0, "max": 2.0}},
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.WRITE,
        ),
        ToolDefinition(
            name="change_max_tokens",
            description="Change the max tokens setting",
            parameters={"max_tokens": {"type": "integer", "min": 1, "max": 100000}},
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.WRITE,
        ),
        ToolDefinition(
            name="update_runtime_configuration",
            description=(
                "Update one or more supported runtime configuration settings after "
                "the user explicitly confirms the proposed change"
            ),
            parameters={
                "changes": {
                    "type": "object",
                    "description": (
                        "Canonical RuntimeUpdate fields plus a config object containing "
                        "temperature, max_tokens, dynamic_routing_enabled, cache_enabled, "
                        "cache_ttl_seconds, top_p, frequency_penalty, or presence_penalty"
                    ),
                }
            },
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.WRITE,
        ),
        ToolDefinition(
            name="sync_sources",
            description="Sync all knowledge sources",
            parameters={},
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.EXECUTE,
        ),
        ToolDefinition(
            name="rebuild_embeddings",
            description="Rebuild all embeddings for the knowledge base",
            parameters={},
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.EXECUTE,
        ),
        ToolDefinition(
            name="clear_cache",
            description="Clear the runtime cache",
            parameters={},
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.EXECUTE,
        ),
        ToolDefinition(
            name="restart_runtime",
            description="Restart the runtime",
            parameters={},
            required_permission=UserRole.ADMIN,
            action_type=ActionType.EXECUTE,
            dangerous=True,
        ),
        ToolDefinition(
            name="run_health_check",
            description="Run a comprehensive health check",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="run_cost_analysis",
            description="Run a detailed cost analysis",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="generate_report",
            description="Generate a comprehensive runtime report",
            parameters={"format": {"type": "string", "enum": ["markdown", "json", "text"]}},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="pause_runtime",
            description="Pause the runtime",
            parameters={},
            required_permission=UserRole.ADMIN,
            action_type=ActionType.EXECUTE,
            dangerous=True,
        ),
        ToolDefinition(
            name="resume_runtime",
            description="Resume a paused runtime",
            parameters={},
            required_permission=UserRole.ADMIN,
            action_type=ActionType.EXECUTE,
        ),
        ToolDefinition(
            name="rotate_api_key",
            description="Rotate the runtime API key",
            parameters={},
            required_permission=UserRole.ADMIN,
            action_type=ActionType.ADMIN,
            dangerous=True,
        ),
        ToolDefinition(
            name="revoke_api_key",
            description="Revoke a specific API key",
            parameters={"key_id": {"type": "string"}},
            required_permission=UserRole.ADMIN,
            action_type=ActionType.ADMIN,
            dangerous=True,
        ),
        ToolDefinition(
            name="test_provider",
            description="Test a provider connection",
            parameters={"provider_name": {"type": "string"}},
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.EXECUTE,
        ),
        ToolDefinition(
            name="test_database",
            description="Test database connectivity and performance",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
        ToolDefinition(
            name="test_tool",
            description="Test a connected tool",
            parameters={"tool_id": {"type": "string"}},
            required_permission=UserRole.DEVELOPER,
            action_type=ActionType.EXECUTE,
        ),
        ToolDefinition(
            name="generate_runtime_summary",
            description="Generate a human-readable runtime summary",
            parameters={},
            required_permission=UserRole.VIEWER,
            action_type=ActionType.READ,
        ),
    ]


def build_user_prompt(user_message: str, context: RuntimeContext) -> str:
    return f"""User request: {user_message}

Current runtime context:
- Runtime ID: {context.runtime_id}
- Status: {context.runtime.get('status', 'unknown')}
- Provider: {context.runtime.get('provider', 'unknown')}
- Model: {context.runtime.get('model', 'unknown')}
- Health Score: {context.health.get('health_score', 'N/A')}
- Monthly Cost: {context.billing.get('monthly_cost', 'N/A')}
- Knowledge Sources: {len(context.knowledge_sources)}
- Tools: {len(context.tools)}
- Error Count: {context.health.get('error_count', 0)}

Available tools:
{_format_tools()}

User role: {context.user_role.value}

Instructions:
1. Analyze the user's request against the runtime context.
2. Determine which tools are needed.
3. Execute tools in the correct order.
4. Synthesize results into a conversational response.
5. Always check permissions before suggesting actions.
6. Provide specific data, not vague statements.
7. If uncertain, say so rather than guessing.
"""


def _format_tools() -> str:
    tools = build_tool_definitions()
    return "\n".join(
        f"- {t.name}: {t.description} (requires {t.required_permission.value})"
        for t in tools
    )


def build_streaming_prompt(user_message: str, context: RuntimeContext) -> str:
    return f"""You are the Zyntry Runtime Assistant.

The user asked: "{user_message}"

Provide a helpful, conversational response about their runtime.
Be specific with numbers and data from the context.
Format your response with markdown bullets where appropriate.
Keep it concise but informative.
"""

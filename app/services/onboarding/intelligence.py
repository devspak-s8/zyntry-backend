from __future__ import annotations

import json
import logging
import re
from typing import Any, AsyncGenerator

import httpx

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.onboarding_intelligence import (
    ApplicationIntegrationRequirement,
    ApplicationRequirements,
    ClarificationQuestion,
    RuntimePlan,
    RuntimePlanComponent,
)
from app.services.integrations.definitions import integration_registry
from app.services.rag import AnthropicLLMProvider, BaseLLMProvider, OpenAILLMProvider

logger = logging.getLogger(__name__)


_USE_CASE_DEFAULTS: dict[str, dict[str, Any]] = {
    "resume_analyzer": {
        "primary_function": "Analyze resumes against job requirements and return structured feedback",
        "target_users": ["job seekers"],
        "inputs": ["resume", "job description"],
        "outputs": ["ATS score", "resume recommendations"],
        "requires_documents": True,
        "requires_external_data": False,
        "requires_tools": False,
        "requires_memory": False,
    },
    "ai_customer_support": {
        "primary_function": "Answer customer questions and assist with support workflows",
        "target_users": ["customers", "support teams"],
        "inputs": ["customer question"],
        "outputs": ["support answer"],
        "requires_documents": False,
        "requires_external_data": False,
        "requires_tools": True,
        "requires_memory": True,
        "memory_scope": "session",
    },
    "developer_ai_assistant": {
        "primary_function": "Analyze software repositories and assist development workflows",
        "target_users": ["developers"],
        "inputs": ["repository content", "developer question"],
        "outputs": ["code analysis", "development recommendations"],
        "requires_documents": False,
        "requires_external_data": False,
        "requires_tools": True,
        "requires_memory": False,
    },
    "autonomous_issue_triage_agent": {
        "primary_function": "Analyze and triage software issues",
        "target_users": ["engineering teams"],
        "inputs": ["issues", "repository context"],
        "outputs": ["issue classification", "triage recommendations"],
        "requires_documents": False,
        "requires_external_data": False,
        "requires_tools": True,
        "requires_memory": False,
    },
    "knowledge_search_rag": {
        "primary_function": "Answer questions using connected knowledge sources",
        "target_users": ["knowledge workers"],
        "inputs": ["user question", "knowledge content"],
        "outputs": ["grounded answer", "source references"],
        "requires_documents": True,
        "requires_external_data": False,
        "requires_tools": True,
        "requires_memory": True,
        "memory_scope": "session",
    },
}


class RuleBasedRequirementsExtractor:
    """Safe fallback and validation baseline for model extraction."""

    async def extract(
        self,
        message: str,
        current: ApplicationRequirements | None = None,
        pending_requirement: str | None = None,
    ) -> ApplicationRequirements:
        text = message.strip()
        lowered = text.lower()
        data = current.model_dump(mode="json") if current else {}

        application_type = self._application_type(lowered, data.get("application_type"))
        data["application_type"] = application_type
        defaults = _USE_CASE_DEFAULTS.get(application_type, {})
        for key, value in defaults.items():
            if data.get(key) in (None, [], ""):
                data[key] = value

        if not data.get("primary_function") and text:
            data["primary_function"] = re.split(r"[.!?]\s", text, maxsplit=1)[0][:1000]

        if any(term in lowered for term in ("student", "course", "university")):
            data["target_users"] = self._merge_list(data.get("target_users"), ["students"])
        elif "employee" in lowered or "internal team" in lowered:
            data["target_users"] = self._merge_list(data.get("target_users"), ["employees"])
        elif "my users" in lowered or "end users" in lowered:
            data["target_users"] = self._merge_list(data.get("target_users"), ["application users"])

        document_terms = ("document", "pdf", "docx", "resume", "cv", "upload", "course material")
        if any(term in lowered for term in document_terms):
            data["requires_documents"] = True
        formats = [fmt for fmt in ("pdf", "docx", "txt", "csv", "markdown", "html") if fmt in lowered]
        if formats:
            data["document_formats"] = self._merge_list(data.get("document_formats"), formats)

        external_terms = (
            "public web",
            "search the web",
            "online",
            "external retrieval",
            "external source",
            "public website",
            "trusted website",
        )
        if any(term in lowered for term in external_terms):
            data["requires_external_data"] = True
        if any(term in lowered for term in ("internal only", "no external", "without external")):
            data["requires_external_data"] = False
        source_types: list[str] = []
        for term, source_type in (
            ("university", "university websites"),
            ("academic", "academic repositories"),
            ("public document", "public documents"),
            ("general web", "general web"),
            ("trusted website", "trusted websites"),
        ):
            if term in lowered:
                source_types.append(source_type)
        if source_types:
            data["external_source_types"] = self._merge_list(
                data.get("external_source_types"), source_types
            )

        integrations = self._extract_integrations(lowered, data.get("integrations", []))
        if integrations:
            data["integrations"] = integrations
            data["requires_tools"] = True

        if any(term in lowered for term in ("remember", "memory", "previous conversation", "follow-up")):
            data["requires_memory"] = True
        if any(term in lowered for term in (
            "no memory",
            "no long-term memory",
            "no long term memory",
            "do not remember",
            "don't remember",
            "independent request",
            "stateless",
        )):
            data["requires_memory"] = False
            data["memory_scope"] = "request"
        if "organization memory" in lowered or "company memory" in lowered:
            data["memory_scope"] = "organization"
        elif "user memory" in lowered or "per user" in lowered:
            data["memory_scope"] = "user"
        elif "session" in lowered or "conversation" in lowered:
            if data.get("requires_memory"):
                data["memory_scope"] = "session"

        if any(term in lowered for term in ("both", "hybrid")):
            data["connection_ownership"] = "hybrid"
        elif any(term in lowered for term in ("my users", "end users", "their own", "user oauth")):
            data["connection_ownership"] = "end_user"
        elif any(term in lowered for term in ("company data", "our data", "my organization", "internal data")):
            data["connection_ownership"] = "company"

        # Preserve an ownership decision already made in the onboarding flow
        # (for example, Mode B / end-user OAuth). Without this, a later
        # clarification turn could lose the decision and the generated plan
        # would incorrectly fall back to company-managed connections.
        if not data.get("connection_ownership"):
            configured_mode = data.get("integration_mode")
            data["connection_ownership"] = {
                "zyntry_managed": "company",
                "end_user_oauth": "end_user",
                "hybrid": "hybrid",
            }.get(configured_mode)

        self._apply_pending_answer(data, pending_requirement, lowered)
        data["confidence"] = max(float(data.get("confidence") or 0), 0.55)
        data["extraction_source"] = "fallback"
        return ApplicationRequirements.model_validate(data)

    # These helpers are shared with the model adapter below. Keeping the
    # fallback implementation available preserves test/dev operation when no
    # provider key is configured, but it is never preferred over the model.
    _application_type = staticmethod(lambda text, current: (
        current
        or ("resume_analyzer" if ("resume" in text or " ats " in f" {text} " or "cv" in text) else
            "ai_customer_support" if ("support" in text or "customer" in text or "order status" in text) else
            "autonomous_issue_triage_agent" if ("triage" in text or ("issue" in text and "github" in text)) else
            "developer_ai_assistant" if ("code" in text or "developer" in text or "repository" in text) else
            "knowledge_search_rag" if any(term in text for term in ("knowledge", "rag", "study", "course material", "research")) else
            "autonomous_ai_agent" if "agent" in text else "general_ai_application")
    ))
    _merge_list = staticmethod(lambda existing, additions: list(dict.fromkeys([*(existing or []), *additions])))
    _extract_integrations = lambda self, text, existing: GeminiLLMProvider._extract_integrations(self, text, existing)
    _apply_pending_answer = staticmethod(lambda data, pending, text: GeminiLLMProvider._apply_pending_answer(data, pending, text))


class GeminiLLMProvider(BaseLLMProvider):
    """Gemini adapter using the public generateContent HTTP API."""

    def __init__(self, api_key: str, base_url: str = "https://generativelanguage.googleapis.com/v1beta") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def generate(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> tuple[str, int]:
        system = next((m["content"] for m in messages if m.get("role") == "system"), "")
        contents = [
            {"role": "model" if m.get("role") == "assistant" else "user", "parts": [{"text": m["content"]}]}
            for m in messages
            if m.get("role") != "system"
        ]
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
        }
        if system:
            payload["systemInstruction"] = {"parts": [{"text": system}]}
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{self._base_url}/models/{model}:generateContent",
                params={"key": self._api_key},
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        content = data["candidates"][0]["content"]["parts"][0]["text"]
        usage = data.get("usageMetadata", {}).get("totalTokenCount", 0)
        return content, usage

    async def astream(
        self,
        messages: list[dict[str, str]],
        model: str,
        max_tokens: int = 2048,
        temperature: float = 0.7,
    ) -> AsyncGenerator[str, None]:
        content, _ = await self.generate(messages, model, max_tokens, temperature)
        yield content

    @staticmethod
    def _application_type(text: str, current: str | None) -> str:
        if current:
            return current
        if "resume" in text or " ats " in f" {text} " or "cv" in text:
            return "resume_analyzer"
        if "support" in text or "customer" in text or "order status" in text:
            return "ai_customer_support"
        if "triage" in text or ("issue" in text and "github" in text):
            return "autonomous_issue_triage_agent"
        if "code" in text or "developer" in text or "repository" in text:
            return "developer_ai_assistant"
        if any(term in text for term in ("knowledge", "rag", "study", "course material", "research")):
            return "knowledge_search_rag"
        if "agent" in text:
            return "autonomous_ai_agent"
        return "general_ai_application"

    @staticmethod
    def _merge_list(existing: list[str] | None, additions: list[str]) -> list[str]:
        return list(dict.fromkeys([*(existing or []), *additions]))

    def _extract_integrations(
        self,
        text: str,
        existing: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_slug = {item.get("slug"): dict(item) for item in existing if item.get("slug")}
        # File formats are document metadata, not external integrations.
        non_integration_slugs = {"pdf", "docx", "txt", "csv", "markdown", "html", "document_storage"}
        for slug in integration_registry.list_slugs():
            if slug in non_integration_slugs:
                continue
            defn = integration_registry.get(slug)
            aliases = {slug, slug.replace("_", " ")}
            if defn:
                aliases.add(defn.name.lower())
            if any(alias in text for alias in aliases):
                by_slug.setdefault(
                    defn.slug if defn else slug,
                    {
                        "slug": defn.slug if defn else slug,
                        "purpose": "Provide application data or actions",
                        "capabilities": [],
                        "write_access": False,
                        "required": True,
                    },
                )
                if defn and defn.slug == "slack" and any(term in text for term in ("post approved repl", "send approved repl", "post replies", "send replies", "send messages")):
                    by_slug[defn.slug]["capabilities"] = ["send_messages"]
                    by_slug[defn.slug]["write_access"] = True
        if "postgres" in text or "sql database" in text:
            by_slug.setdefault("postgresql", {"slug": "postgresql", "purpose": "Structured data access"})
        if "web crawl" in text or "website crawl" in text:
            by_slug.setdefault("website", {"slug": "website", "purpose": "Approved website retrieval"})
        return list(by_slug.values())

    @staticmethod
    def _apply_pending_answer(data: dict[str, Any], pending: str | None, text: str) -> None:
        if pending == "requires_documents":
            data["requires_documents"] = not any(term in text for term in ("no", "none", "not needed"))
        elif pending == "requires_external_data":
            data["requires_external_data"] = not any(term in text for term in ("no", "internal only"))
        elif pending == "requires_tools":
            data["requires_tools"] = not any(term in text for term in ("no", "none", "not needed"))
        elif pending == "requires_memory":
            data["requires_memory"] = not any(term in text for term in ("no", "stateless", "independent"))
        elif pending == "memory_scope":
            for scope in ("organization", "user", "session", "request"):
                if scope in text:
                    data["memory_scope"] = scope
                    break
        elif pending == "connection_ownership":
            if "both" in text or "hybrid" in text:
                data["connection_ownership"] = "hybrid"
            elif "user" in text or "their own" in text:
                data["connection_ownership"] = "end_user"
            elif "company" in text or "organization" in text or "internal" in text:
                data["connection_ownership"] = "company"


class ModelBackedRequirementsExtractor:
    """Model-first extraction with strict validation and a deterministic fallback."""

    def __init__(
        self,
        provider: BaseLLMProvider | None = None,
        model: str | None = None,
        fallback: RuleBasedRequirementsExtractor | None = None,
    ) -> None:
        self.provider = provider if provider is not None else self._configured_provider()
        self.model = model or getattr(settings, "ONBOARDING_MODEL", "gpt-4o-mini")
        self.fallback = fallback or RuleBasedRequirementsExtractor()

    async def extract(
        self,
        message: str,
        current_data: dict[str, Any] | None = None,
        history: list[dict[str, Any]] | None = None,
        pending_requirement: str | None = None,
    ) -> ApplicationRequirements:
        current = self._validated_current(current_data)
        baseline = await self.fallback.extract(message, current, pending_requirement)
        if self.provider is None:
            return baseline

        try:
            content, _ = await self.provider.generate(
                messages=[
                    {"role": "system", "content": self._system_prompt()},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "current_requirements": current.model_dump(mode="json") if current else None,
                                "pending_requirement": pending_requirement,
                                "recent_conversation": (history or [])[-8:],
                                "latest_message": message,
                            },
                            default=str,
                        ),
                    },
                ],
                model=self.model,
                max_tokens=1800,
                temperature=0.0,
            )
            extracted = ApplicationRequirements.model_validate(self._parse_json(content))
            merged = self._merge(baseline, extracted)
            merged.extraction_source = "hybrid"
            return merged
        except (ValidationError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            logger.warning("Onboarding model returned invalid requirements; using validated fallback")
        except Exception:
            logger.exception("Onboarding model extraction failed; using validated fallback")
        return baseline

    @staticmethod
    def _configured_provider() -> BaseLLMProvider | None:
        preferred = getattr(settings, "ONBOARDING_PROVIDER", "openai").lower()
        if preferred == "google" and settings.GOOGLE_API_KEY:
            return GeminiLLMProvider(settings.GOOGLE_API_KEY)
        if preferred == "gemini" and settings.GOOGLE_API_KEY:
            return GeminiLLMProvider(settings.GOOGLE_API_KEY)
        if preferred == "anthropic" and settings.ANTHROPIC_API_KEY:
            return AnthropicLLMProvider(settings.ANTHROPIC_API_KEY)
        if preferred == "openai" and settings.OPENAI_API_KEY:
            return OpenAILLMProvider(settings.OPENAI_API_KEY)
        if settings.OPENAI_API_KEY:
            return OpenAILLMProvider(settings.OPENAI_API_KEY)
        if settings.ANTHROPIC_API_KEY:
            return AnthropicLLMProvider(settings.ANTHROPIC_API_KEY)
        return None

    @staticmethod
    def _validated_current(data: dict[str, Any] | None) -> ApplicationRequirements | None:
        if not data:
            return None
        try:
            return ApplicationRequirements.model_validate(data)
        except ValidationError:
            logger.warning("Ignoring invalid stored application requirements")
            return None

    @staticmethod
    def _parse_json(content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end < start:
            raise ValueError("Model response did not contain a JSON object")
        value = json.loads(cleaned[start : end + 1])
        if not isinstance(value, dict):
            raise ValueError("Model response must be a JSON object")
        return value

    @staticmethod
    def _merge(
        baseline: ApplicationRequirements,
        extracted: ApplicationRequirements,
    ) -> ApplicationRequirements:
        result = baseline.model_dump(mode="json")
        model_data = extracted.model_dump(mode="json", exclude_unset=True)
        list_fields = {
            "target_users",
            "inputs",
            "outputs",
            "document_formats",
            "external_source_types",
            "requested_actions",
            "constraints",
            "assumptions",
        }
        for key, value in model_data.items():
            if key in list_fields:
                if value:
                    result[key] = list(dict.fromkeys([*result.get(key, []), *value]))
            elif key == "integrations":
                by_slug = {item["slug"]: item for item in result.get("integrations", [])}
                for item in value or []:
                    defn = integration_registry.get(item.get("slug", ""))
                    if defn:
                        item["slug"] = defn.slug
                        by_slug[defn.slug] = {**by_slug.get(defn.slug, {}), **item}
                result[key] = list(by_slug.values())
            elif value is not None and value != "":
                result[key] = value
        result["confidence"] = max(baseline.confidence, extracted.confidence)
        return ApplicationRequirements.model_validate(result)

    @staticmethod
    def _system_prompt() -> str:
        return """You extract application infrastructure requirements for Zyntry onboarding.
Return one JSON object matching ApplicationRequirements schema version 1.0.
Use null when a requirement is genuinely unknown. Never invent integrations, users, inputs,
outputs, actions, scale, or compliance requirements. Preserve facts from current_requirements.
Classify company-owned connections, end-user connections, or hybrid ownership explicitly.
Only use integration slugs from the supplied conversation and common canonical slugs such as
github, gitlab, slack, notion, postgresql, redis, website, and document_storage.
Do not include markdown, explanation, credentials, or hidden reasoning."""


class AdaptiveClarificationService:
    _QUESTIONS: dict[str, ClarificationQuestion] = {
        "application_type": ClarificationQuestion(
            requirement="application_type",
            question="What is the main kind of AI application you are building?",
            suggested_answers=["Customer support", "Knowledge assistant", "Developer tool", "Something else"],
        ),
        "primary_function": ClarificationQuestion(
            requirement="primary_function",
            question="What is the single most important job this application should perform?",
            suggested_answers=["Answer questions", "Analyze content", "Perform actions", "Help me define it"],
        ),
        "target_users": ClarificationQuestion(
            requirement="target_users",
            question="Who will primarily use this application?",
            suggested_answers=["My internal team", "My customers", "Developers", "Students"],
        ),
        "inputs": ClarificationQuestion(
            requirement="inputs",
            question="What information will users give the application?",
            suggested_answers=["Questions or chat messages", "Uploaded documents", "Connected account data", "Structured records"],
        ),
        "outputs": ClarificationQuestion(
            requirement="outputs",
            question="What should the application return or accomplish for the user?",
            suggested_answers=["Natural-language answers", "Structured analysis", "Recommendations", "Actions in another system"],
        ),
        "requires_documents": ClarificationQuestion(
            requirement="requires_documents",
            question="Will the application process uploaded or connected documents?",
            suggested_answers=["Yes, users will upload documents", "Yes, from connected sources", "No documents", "Not initially"],
        ),
        "document_formats": ClarificationQuestion(
            requirement="document_formats",
            question="Which document formats should the runtime accept?",
            suggested_answers=["PDF and DOCX", "PDF only", "PDF, DOCX, and TXT", "All supported formats"],
        ),
        "external_source_types": ClarificationQuestion(
            requirement="external_source_types",
            question="Which external sources should the runtime be allowed to use?",
            suggested_answers=["Trusted websites", "Academic and official sources", "General public web", "Approved domains only"],
        ),
        "requires_external_data": ClarificationQuestion(
            requirement="requires_external_data",
            question="Should the runtime retrieve information from external public sources when internal data is insufficient?",
            suggested_answers=["Internal sources only", "Approved websites only", "Trusted public web", "Not initially"],
        ),
        "requires_tools": ClarificationQuestion(
            requirement="requires_tools",
            question="Does the application need to read from or perform actions in another system?",
            suggested_answers=["Yes, read connected systems", "Yes, perform confirmed actions", "No external systems", "Not initially"],
        ),
        "integrations": ClarificationQuestion(
            requirement="integrations",
            question="Which systems must the application read from or act in?",
            suggested_answers=["GitHub and Slack", "PostgreSQL", "Uploaded documents", "No external systems"],
        ),
        "connection_ownership": ClarificationQuestion(
            requirement="connection_ownership",
            question="Who will connect these systems?",
            suggested_answers=["My company", "My application users", "Both", "Not sure yet"],
        ),
        "requires_memory": ClarificationQuestion(
            requirement="requires_memory",
            question="Should the runtime remember relevant context beyond a single request?",
            suggested_answers=["Current session", "Per user", "Organization-wide", "No memory"],
        ),
        "memory_scope": ClarificationQuestion(
            requirement="memory_scope",
            question="How long should the runtime remember conversation context?",
            suggested_answers=["Current session", "Per user", "Across the organization", "No persistent memory"],
        ),
    }

    def next_question(self, requirements: ApplicationRequirements) -> ClarificationQuestion | None:
        for missing in requirements.missing_requirements():
            question = self._QUESTIONS.get(missing)
            if question:
                return question
        return None


class RuntimePlanGenerator:
    SCHEMA_VERSION = "1.0"

    def generate(
        self,
        requirements: ApplicationRequirements,
        configuration: dict[str, Any],
        previous_plan: dict[str, Any] | None = None,
    ) -> RuntimePlan:
        fingerprint = requirements.fingerprint()
        previous_version = int((previous_plan or {}).get("plan_version", 0) or 0)
        model_routing = {
            "provider": configuration.get("provider", "openai"),
            "model": configuration.get("model", "gpt-4o"),
            "strategy": configuration.get("routing_strategy", "balanced"),
            "fallback_models": configuration.get("fallback_models", []),
        }
        deployment = {
            "environment": configuration.get("environment", "development"),
            "expected_scale": requirements.expected_scale or "prototype",
            "provisioning_mode": "project_first",
        }
        same_plan = (
            (previous_plan or {}).get("requirements_fingerprint") == fingerprint
            and (previous_plan or {}).get("model_routing") == model_routing
            and (previous_plan or {}).get("deployment") == deployment
        )
        version = max(previous_version, 1) if same_plan else previous_version + 1
        unresolved = requirements.missing_requirements()

        components = [
            RuntimePlanComponent(
                key="ai_reasoning",
                name="AI reasoning",
                reason="The application requires model-backed understanding and response generation.",
                configuration={"structured_output": bool(requirements.outputs)},
            )
        ]
        if requirements.requires_documents:
            components.append(
                RuntimePlanComponent(
                    key="document_processing",
                    name="Document processing",
                    reason="The application accepts or retrieves document content.",
                    configuration={"formats": requirements.document_formats, "vector_store": configuration.get("vector_store", "pgvector")},
                    depends_on=["ai_reasoning"],
                )
            )
        if requirements.requires_external_data:
            components.append(
                RuntimePlanComponent(
                    key="external_retrieval",
                    name="External retrieval",
                    reason="The application needs information outside connected internal sources.",
                    configuration={
                        "source_types": requirements.external_source_types,
                        "require_citations": True,
                        "source_validation": "strict",
                    },
                    depends_on=["ai_reasoning"],
                )
            )
        if requirements.requires_memory:
            components.append(
                RuntimePlanComponent(
                    key="memory",
                    name="Conversation memory",
                    reason="The application must preserve relevant context across requests.",
                    configuration={"scope": requirements.memory_scope or "session"},
                    depends_on=["ai_reasoning"],
                )
            )

        integration_policies: list[dict[str, Any]] = []
        default_mode = {
            "company": "zyntry_managed",
            "end_user": "end_user_oauth",
            "hybrid": "hybrid",
        }.get(requirements.connection_ownership or "company", "zyntry_managed")
        non_integration_slugs = {"pdf", "docx", "txt", "csv", "markdown", "html", "json", "document_storage"}
        planned_integrations = [
            item for item in requirements.integrations
            if item.slug not in non_integration_slugs
        ]
        planned_slugs = {item.slug for item in planned_integrations}
        # For legacy/document-only drafts with no requested integrations, keep
        # the document storage component discoverable. Explicit integration
        # lists remain authoritative and are never augmented.
        if not planned_integrations and requirements.requires_documents and "document_storage" not in planned_slugs:
            planned_integrations.append(
                ApplicationIntegrationRequirement(
                    slug="document_storage",
                    purpose="Accept and index application documents",
                    ownership="company",
                )
            )
        for integration in planned_integrations:
            defn = integration_registry.get(integration.slug)
            if not defn:
                continue
            integration_mode = integration.ownership or requirements.connection_ownership
            mode = {
                "company": "zyntry_managed",
                "end_user": "end_user_oauth",
                "hybrid": "hybrid",
            }.get(integration_mode or "company", default_mode)
            supports_hybrid = {"zyntry_managed", "end_user_oauth"}.issubset(
                defn.supported_connection_modes
            )
            if mode == "hybrid" and not supports_hybrid:
                mode = "zyntry_managed"
            elif mode not in defn.supported_connection_modes and mode != "hybrid":
                mode = defn.supported_connection_modes[0]
            default_read_capabilities = [
                capability.slug for capability in defn.capabilities if not capability.is_write
            ]
            capabilities = list(dict.fromkeys([
                *default_read_capabilities,
                *integration.capabilities,
            ]))
            write_capability_slugs = {
                capability.slug for capability in defn.capabilities if capability.is_write
            }
            read_capabilities = [
                capability for capability in capabilities
                if capability not in write_capability_slugs
            ]
            write_capabilities = [
                capability for capability in capabilities
                if capability in write_capability_slugs
            ]
            integration_policies.append(
                {
                    "integration_slug": defn.slug,
                    "connection_mode": mode,
                    "enabled_capabilities": capabilities,
                    "read_capabilities": read_capabilities,
                    "write_capabilities": write_capabilities,
                    "requires_confirmation": bool(write_capabilities),
                    "write_access": integration.write_access,
                    "required": integration.required,
                    "purpose": integration.purpose,
                }
            )
            components.append(
                RuntimePlanComponent(
                    key=f"integration:{defn.slug}",
                    name=defn.name,
                    reason=integration.purpose or "Required by the application workflow.",
                    configuration={"connection_mode": mode, "capabilities": capabilities},
                    depends_on=["ai_reasoning"],
                )
            )

        components.extend(
            [
                RuntimePlanComponent(
                    key="security",
                    name="Security and isolation",
                    reason="Every runtime requires tenant isolation and permission enforcement.",
                    configuration={"read_only_by_default": True, "data_sensitivity": requirements.data_sensitivity or "internal"},
                ),
                RuntimePlanComponent(
                    key="observability",
                    name="Observability",
                    reason="Runtime behavior, cost, latency, and failures must be explainable.",
                    configuration={"logs": True, "metrics": True, "audit": True},
                ),
                RuntimePlanComponent(
                    key="api",
                    name="Authenticated runtime API",
                    reason="The developer application invokes the runtime through an authenticated endpoint.",
                    configuration={"authentication": "api_key"},
                    depends_on=["security"],
                ),
            ]
        )

        application_type = requirements.application_type or "general_ai_application"
        return RuntimePlan(
            plan_version=max(version, 1),
            status="clarification_required" if unresolved else "validated",
            requirements_fingerprint=fingerprint,
            application_type=application_type,
            summary=requirements.primary_function or application_type.replace("_", " ").title(),
            components=components,
            integration_policies=integration_policies,
            model_routing=model_routing,
            security={"read_only_by_default": True, "confirmation_for_writes": True},
            observability={"enabled": True, "record_evidence": True},
            deployment=deployment,
            assumptions=requirements.assumptions,
            unresolved_requirements=unresolved,
        )

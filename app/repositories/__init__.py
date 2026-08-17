from __future__ import annotations

from app.core.database import AsyncSession
from app.repositories.actions import ActionAuditLogRepository, ActionConfirmationRepository, ActionExecutionRepository
from app.repositories.analytics import UsageEventRepository
from app.repositories.apikeys import ApiKeyRepository
from app.repositories.billing import (
    BudgetRepository,
    PricingRuleRepository,
    UsageLogRepository,
    WalletRepository,
    WalletTransactionRepository,
)
from app.repositories.embedding_cache import EmbeddingCacheRepository
from app.repositories.events import EventRepository
from app.repositories.health_metrics import HealthMetricRepository, RuntimeHealthCheckRepository
from app.repositories.integrations import IntegrationConnectionRepository, RuntimeIntegrationRepository
from app.repositories.knowledge import (
    DocumentRepository,
    KnowledgeBaseRepository,
    KnowledgeSourceRepository,
    SyncJobRepository,
    SyncScheduleRepository,
)
from app.repositories.memory import MemoryRecordRepository
from app.repositories.notifications import NotificationRepository
from app.repositories.oauth import OAuthConnectionRepository, OAuthProviderRepository, OAuthStateRepository
from app.repositories.onboarding import OnboardingStateRepository
from app.repositories.onboarding_session import OnboardingSessionRepository
from app.repositories.organizations import OrganizationRepository
from app.repositories.projects import ProjectRepository
from app.repositories.providers import ProviderConnectionRepository
from app.repositories.request_logs import RequestLogRepository
from app.repositories.runtimes import RuntimeBuildChunkRepository, RuntimeBuildLogRepository, RuntimeRepository
from app.repositories.tools import ToolRepository
from app.repositories.users import UserRepository
from app.repositories.webhook_deliveries import WebhookDeliveryRepository
from app.repositories.webhooks import WebhookSubscriptionRepository
from app.repositories.workflows import WorkflowExecutionRepository, WorkflowRepository


class UnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.organizations = OrganizationRepository(session)
        self.projects = ProjectRepository(session)
        self.users = UserRepository(session)
        self.api_keys = ApiKeyRepository(session)
        self.providers = ProviderConnectionRepository(session)
        self.onboarding = OnboardingStateRepository(session)
        self.onboarding_sessions = OnboardingSessionRepository(session)
        self.knowledge_bases = KnowledgeBaseRepository(session)
        self.documents = DocumentRepository(session)
        self.knowledge_sources = KnowledgeSourceRepository(session)
        self.sync_jobs = SyncJobRepository(session)
        self.sync_schedules = SyncScheduleRepository(session)
        self.memory_records = MemoryRecordRepository(session)
        self.tools = ToolRepository(session)
        self.analytics = UsageEventRepository(session)
        self.webhook_subscriptions = WebhookSubscriptionRepository(session)
        self.webhook_deliveries = WebhookDeliveryRepository(session)
        self.events = EventRepository(session)
        self.request_logs = RequestLogRepository(session)
        self.runtimes = RuntimeRepository(session)
        self.runtime_build_logs = RuntimeBuildLogRepository(session)
        self.runtime_build_chunks = RuntimeBuildChunkRepository(session)
        self.runtime_integrations = RuntimeIntegrationRepository(session)
        self.integration_connections = IntegrationConnectionRepository(session)
        self.notifications = NotificationRepository(session)
        self.embedding_caches = EmbeddingCacheRepository(session)
        self.health_metrics = HealthMetricRepository(session)
        self.runtime_health_checks = RuntimeHealthCheckRepository(session)
        self.workflows = WorkflowRepository(session)
        self.workflow_executions = WorkflowExecutionRepository(session)
        self.actions = ActionExecutionRepository(session)
        self.action_confirmations = ActionConfirmationRepository(session)
        self.action_audit_logs = ActionAuditLogRepository(session)
        self.oauth_providers = OAuthProviderRepository(session)
        self.oauth_connections = OAuthConnectionRepository(session)
        self.oauth_states = OAuthStateRepository(session)
        self.wallets = WalletRepository(session)
        self.wallet_transactions = WalletTransactionRepository(session)
        self.pricing_rules = PricingRuleRepository(session)
        self.usage_logs = UsageLogRepository(session)
        self.budgets = BudgetRepository(session)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()

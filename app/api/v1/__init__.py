from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.v1.actions.router import router as actions_router
from app.api.v1.admin.router import router as admin_router
from app.api.v1.analytics.router import router as analytics_router
from app.api.v1.apikeys.router import router as apikeys_router
from app.api.v1.auth.router import router as auth_router
from app.api.v1.billing.router import router as billing_router
from app.api.v1.chat.router import router as chat_router
from app.api.v1.connections.router import router as connections_router
from app.api.v1.embeddings.router import router as embeddings_router
from app.api.v1.events.router import router as events_router
from app.api.v1.features.dependencies import require_action_feature, require_feature
from app.api.v1.features.router import router as features_router
from app.api.v1.integrations.router import router as integrations_router
from app.api.v1.invoke.router import router as invoke_router
from app.api.v1.knowledge.router import router as knowledge_router
from app.api.v1.logs.router import router as logs_router
from app.api.v1.memory.router import router as memory_router
from app.api.v1.models.router import router as models_router
from app.api.v1.notifications.router import router as notifications_router
from app.api.v1.oauth.router import router as oauth_router
from app.api.v1.onboarding.router import router as onboarding_router
from app.api.v1.organizations.router import router as organizations_router
from app.api.v1.projects.router import router as projects_router
from app.api.v1.providers.router import router as providers_router
from app.api.v1.router.router import router as router_router
from app.api.v1.runtime_assistant.router import router as runtime_assistant_router
from app.api.v1.runtimes.router import router as runtimes_router
from app.api.v1.tools.router import router as tools_router
from app.api.v1.users.router import router as users_router
from app.api.v1.webhooks.router import router as webhooks_router
from app.api.v1.workflows.router import router as workflows_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(organizations_router)
api_router.include_router(projects_router)
api_router.include_router(
    runtimes_router, dependencies=[Depends(require_feature("runtime_management"))]
)
api_router.include_router(onboarding_router)
api_router.include_router(integrations_router)
api_router.include_router(connections_router)
api_router.include_router(
    knowledge_router, dependencies=[Depends(require_feature("knowledge_bases"))]
)
api_router.include_router(
    memory_router, dependencies=[Depends(require_feature("runtime_console"))]
)
api_router.include_router(
    chat_router, dependencies=[Depends(require_feature("runtime_console"))]
)
api_router.include_router(
    embeddings_router, dependencies=[Depends(require_feature("runtime_console"))]
)
api_router.include_router(invoke_router)
api_router.include_router(
    router_router, dependencies=[Depends(require_feature("model_routing"))]
)
api_router.include_router(
    models_router, dependencies=[Depends(require_feature("ai_models"))]
)
api_router.include_router(
    providers_router, dependencies=[Depends(require_feature("provider_connections"))]
)
api_router.include_router(
    tools_router, dependencies=[Depends(require_feature("tools_connectors"))]
)
api_router.include_router(
    workflows_router, dependencies=[Depends(require_feature("workflows"))]
)
api_router.include_router(
    analytics_router, dependencies=[Depends(require_feature("analytics"))]
)
api_router.include_router(billing_router)
api_router.include_router(
    apikeys_router, dependencies=[Depends(require_feature("api_keys"))]
)
api_router.include_router(admin_router)
api_router.include_router(
    webhooks_router, dependencies=[Depends(require_feature("webhooks"))]
)
api_router.include_router(
    events_router, dependencies=[Depends(require_feature("observability"))]
)
api_router.include_router(features_router)
api_router.include_router(
    logs_router, dependencies=[Depends(require_feature("observability"))]
)
api_router.include_router(notifications_router)
api_router.include_router(
    runtime_assistant_router,
    dependencies=[Depends(require_feature("runtime_assistant_beta"))],
)
api_router.include_router(
    actions_router, dependencies=[Depends(require_action_feature("actions"))]
)
api_router.include_router(oauth_router)

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin.analytics_router import router as analytics_router
from app.api.v1.admin.api_keys_router import router as api_keys_router
from app.api.v1.admin.audit_logs_router import router as audit_logs_router
from app.api.v1.admin.auth_router import router as auth_router
from app.api.v1.admin.billing_router import router as billing_router
from app.api.v1.admin.dashboard_router import router as dashboard_router
from app.api.v1.admin.events_router import router as events_router
from app.api.v1.admin.feature_flags_router import router as feature_flags_router
from app.api.v1.admin.fingerprints_router import router as fingerprints_router
from app.api.v1.admin.health_router import router as health_router
from app.api.v1.admin.ip_intelligence_router import router as ip_intelligence_router
from app.api.v1.admin.models_router import router as models_router
from app.api.v1.admin.notifications_router import router as notifications_router
from app.api.v1.admin.requests_router import router as requests_router
from app.api.v1.admin.runtimes_router import router as runtimes_router
from app.api.v1.admin.security_router import router as security_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(dashboard_router)
router.include_router(requests_router)
router.include_router(security_router)
router.include_router(ip_intelligence_router)
router.include_router(fingerprints_router)
router.include_router(runtimes_router)
router.include_router(models_router)
router.include_router(billing_router)
router.include_router(analytics_router)
router.include_router(api_keys_router)
router.include_router(events_router)
router.include_router(health_router)
router.include_router(audit_logs_router)
router.include_router(feature_flags_router)
router.include_router(notifications_router)

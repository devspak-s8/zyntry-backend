from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.constants import AlertStatus, risk_level_from_score
from app.admin.models import IPRecord, LoginEvent, SecurityAlert
from app.admin.repositories import IPRecordRepository, LoginEventRepository, SecurityAlertRepository
from app.admin.services.notifications import AdminNotificationService


class SecurityEngine:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._ip_repo = IPRecordRepository(db)
        self._login_repo = LoginEventRepository(db)
        self._alert_repo = SecurityAlertRepository(db)
        self._notify = AdminNotificationService(db)

    def _get_patterns(self) -> dict[str, list[str]]:
        return {
            "sql_injection": [
                r"(?:union\s+select|select\s+.*\s+from)",
                r"(?:drop\s+table|alter\s+table|insert\s+into)",
                r"(?:delete\s+from|update\s+.*\s+set)",
                r"(?:--|\|\||&&|;--)",
                r"(?:exec\s+|execute\s+|xp_cmdshell)",
                r"(?:char\s*\(|concat\s*\(|information_schema)",
            ],
            "xss": [
                r"<script[^>]*>.*?</script>",
                r"javascript\s*:",
                r"on\w+\s*=",
                r"<iframe[^>]*>",
                r"<object[^>]*>",
                r"<embed[^>]*>",
            ],
            "path_traversal": [
                r"\.\./",
                r"\.\.\\",
                r"/etc/passwd",
                r"/etc/shadow",
                r"c:\\windows\\system32",
            ],
            "ssrf": [
                r"https?://127\.0\.0\.1",
                r"https?://localhost",
                r"https?://169\.254\.169\.254",
                r"https?://0\.0\.0\.0",
            ],
            "prompt_injection": [
                r"ignore\s+previous\s+instructions",
                r"system\s+prompt",
                r"you\s+are\s+now",
                r"forget\s+your\s+instructions",
                r"output\s+the\s+prompt",
            ],
        }

    async def analyze_payload(self, content: str, content_type: str = "text") -> dict[str, Any]:
        patterns = self._get_patterns()
        result = {"threats": [], "risk_score": 0}

        for name, pattern_list in patterns.items():
            for pattern in pattern_list:
                if re.search(pattern, content, re.IGNORECASE):
                    result["threats"].append({"type": name, "pattern": pattern})
                    result["risk_score"] += 10

        return result

    async def calculate_risk_score(
        self,
        threat_types: list[str],
        ip_address: str | None,
        user_id: str | None,
        organization_id: str | None,
        is_vpn: bool = False,
        is_proxy: bool = False,
        is_tor: bool = False,
        failed_auth_count: int = 0,
        request_rate: int = 0,
        payload_size: int = 0,
        is_impossible_travel: bool = False,
        multiple_account_creation: bool = False,
        multiple_api_key_gen: bool = False,
    ) -> int:
        score = 0
        threat_weights = {
            "sql_injection": 25,
            "xss": 20,
            "path_traversal": 20,
            "ssrf": 25,
            "prompt_injection": 30,
            "api_key_brute_force": 20,
            "ddos_attempt": 15,
            "credential_stuffing": 20,
            "oversized_payload": 10,
            "impossible_travel": 30,
            "multiple_account_creation": 15,
            "multiple_api_key_gen": 10,
            "wallet_abuse": 25,
            "api_abuse": 10,
            "webhook_forgery": 20,
        }

        for threat in threat_types:
            score += threat_weights.get(threat, 5)

        if is_vpn or is_proxy or is_tor:
            score += 10

        if failed_auth_count > 5:
            score += 15

        if request_rate > 100:
            score += 10

        if payload_size > 1000000:
            score += 5

        if is_impossible_travel:
            score += 20

        if multiple_account_creation:
            score += 15

        if multiple_api_key_gen:
            score += 10

        return min(100, score)

    async def check_brute_force(self, ip_address: str, time_window: int = 60, threshold: int = 5) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(seconds=time_window)
        count = await self._login_repo.get_failures_by_ip(ip_address, hours=time_window // 60)
        return {"detected": count >= threshold, "count": count, "threshold": threshold, "ip_address": ip_address}

    async def check_ddos(self, ip_address: str, time_window: int = 60, threshold: int = 100) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(seconds=time_window)
        count = await self._login_repo.get_failures_by_ip(ip_address, hours=time_window // 60)
        return {"detected": count >= threshold, "count": count, "threshold": threshold, "ip_address": ip_address}

    async def check_excessive_failed_auth(self, user_id: str, time_window: int = 60, threshold: int = 3) -> dict[str, Any]:
        since = datetime.now(UTC) - timedelta(seconds=time_window)
        count = await self._login_repo.get_failures_by_user(user_id, hours=time_window // 60)
        return {"detected": count >= threshold, "count": count, "threshold": threshold, "user_id": user_id}

    async def check_multiple_account_creation(self, ip_address: str, time_window: int = 3600, threshold: int = 3) -> dict[str, Any]:
        return {"detected": False, "ip_address": ip_address, "threshold": threshold}

    async def check_credential_stuffing(self, ip_address: str, time_window: int = 3600, threshold: int = 10) -> dict[str, Any]:
        return {"detected": False, "ip_address": ip_address, "threshold": threshold}

    async def check_impossible_travel(self, fingerprint_id: str, user_id: str, max_distance_km: float = 1000, time_window_hours: int = 24) -> dict[str, Any]:
        return {"detected": False, "user_id": user_id, "fingerprint_id": fingerprint_id}

    async def check_wallet_abuse(self, user_id: str, time_window: int = 3600, threshold: int = 5) -> dict[str, Any]:
        return {"detected": False, "user_id": user_id, "threshold": threshold}

    async def check_api_abuse(self, api_key_id: str, time_window: int = 3600, threshold: int = 1000) -> dict[str, Any]:
        return {"detected": False, "api_key_id": api_key_id, "threshold": threshold}

    async def check_webhook_forgery(self, ip_address: str) -> dict[str, Any]:
        return {"detected": False, "ip_address": ip_address}

    async def analyze_request(
        self,
        ip_address: str,
        user_id: str | None,
        organization_id: str | None,
        payload: str | None = None,
        payload_size: int = 0,
        api_key_id: str | None = None,
    ) -> dict[str, Any]:
        threat_types = []
        analysis = {"ip_address": ip_address, "threats": [], "risk_score": 0}

        if payload:
            result = await self.analyze_payload(payload)
            for threat in result.get("threats", []):
                threat_types.append(threat["type"])
                analysis["threats"].append(threat)

        if threat_types:
            analysis["risk_score"] = await self.calculate_risk_score(
                threat_types=threat_types,
                ip_address=ip_address,
                user_id=user_id,
                organization_id=organization_id,
            )

        return analysis

    async def run_security_scan(self, window_minutes: int = 60, threshold: int = 5) -> dict[str, Any]:
        """Scan recent failed admin logins and create actionable alerts.

        The scan is intentionally idempotent: an open brute-force alert for an
        IP is reused instead of creating a new alert on every scan.
        """
        window_minutes = max(1, min(window_minutes, 24 * 60))
        threshold = max(1, threshold)
        since = datetime.now(UTC) - timedelta(minutes=window_minutes)
        result = await self.db.execute(
            select(LoginEvent.ip_address, func.count(LoginEvent.id).label("failures"))
            .where(
                LoginEvent.created_at >= since,
                LoginEvent.success.is_(False),
                LoginEvent.ip_address.is_not(None),
            )
            .group_by(LoginEvent.ip_address)
        )

        suspicious: list[dict[str, Any]] = []
        alerts_created = 0
        for ip_address, failures in result.all():
            failures = int(failures or 0)
            if failures < threshold:
                continue
            suspicious.append({"ip_address": ip_address, "failed_attempts": failures})
            existing = await self.db.scalar(
                select(SecurityAlert)
                .where(
                    SecurityAlert.alert_type == "brute_force",
                    SecurityAlert.ip_address == ip_address,
                    SecurityAlert.status == AlertStatus.OPEN.value,
                )
                .limit(1)
            )
            if existing is None:
                score = await self.calculate_risk_score(
                    threat_types=["api_key_brute_force"],
                    ip_address=ip_address,
                    user_id=None,
                    organization_id=None,
                    failed_auth_count=failures,
                )
                await self.generate_alert(
                    alert_type="brute_force",
                    risk_score=score,
                    title="Repeated failed authentication attempts",
                    description=f"{failures} failed sign-in attempts from {ip_address} in the last {window_minutes} minutes.",
                    ip_address=ip_address,
                    organization_id=None,
                    user_id=None,
                    fingerprint_hash=None,
                    triggered_rules=["failed_auth_threshold"],
                    metadata={"window_minutes": window_minutes, "failed_attempts": failures},
                )
                await self._ip_repo.ban_ip(
                    ip_address,
                    ban_type="temporary",
                    reason="Automated security scan: repeated failed authentication",
                    duration_hours=24,
                )
                alerts_created += 1

        await self.db.commit()
        return {
            "status": "completed",
            "window_minutes": window_minutes,
            "threshold": threshold,
            "suspicious_ips": suspicious,
            "alerts_created": alerts_created,
        }

    async def generate_alert(
        self,
        alert_type: str,
        risk_score: int,
        title: str,
        description: str | None,
        ip_address: str | None,
        organization_id: str | None,
        user_id: str | None,
        fingerprint_hash: str | None,
        triggered_rules: list[str] | None,
        metadata: dict[str, Any] | None,
    ) -> SecurityAlert:
        risk_level = risk_level_from_score(risk_score)
        alert = SecurityAlert(
            alert_type=alert_type,
            risk_score=risk_score,
            risk_level=risk_level.value,
            title=title,
            description=description,
            ip_address=ip_address,
            organization_id=organization_id,
            user_id=user_id,
            fingerprint_hash=fingerprint_hash,
            triggered_rules=triggered_rules,
            metadata_=metadata,
        )
        self.db.add(alert)
        await self.db.flush()
        await self._notify.alert_generated(alert)
        return alert

    async def get_alert_timeline(self, alert_id: str) -> list[dict[str, Any]]:
        result = await self.db.execute(select(SecurityAlert).where(SecurityAlert.id == alert_id))
        alert = result.scalar_one_or_none()
        if alert is None:
            return []

        events = [
            {
                "id": f"{alert.id}:created",
                "alert_id": str(alert.id),
                "action": "Alert Created",
                "performed_by": None,
                "reason": alert.description,
                "created_at": alert.first_seen.isoformat() if alert.first_seen else "",
            }
        ]

        return events

    async def enrich_ip_record(self, ip_address: str, record: IPRecord | None) -> IPRecord:
        if record is None:
            record = IPRecord(ip_address=ip_address)
            self.db.add(record)
            await self.db.flush()
        return record

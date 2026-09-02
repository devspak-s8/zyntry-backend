"""Google Workspace and Google Cloud knowledge-source connectors.

The connectors intentionally use Google's REST APIs directly.  This keeps the
runtime image small and makes each provider's requested resource explicit in
the source configuration.  All sync operations are read-only; write actions
are exposed separately through the action layer and require confirmation.
"""

from __future__ import annotations

import base64
import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from app.services.connectors import registry
from app.services.connectors.base import BaseConnector, ConnectorAuthError


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GoogleApiConnector(BaseConnector):
    """Small common REST connector for Google APIs."""

    service_slug = "google_api"
    base_url = "https://www.googleapis.com"

    def __init__(
        self,
        project_id: str,
        source_id: str,
        config: dict,
        credentials: dict | None = None,
    ) -> None:
        super().__init__(project_id, source_id, config, credentials)
        self._token = (
            (credentials or {}).get("access_token")
            or (credentials or {}).get("token")
            or config.get("access_token")
            or config.get("token")
        )
        self._api_key = (credentials or {}).get("api_key") or config.get("api_key")
        raw_service_account = (
            (credentials or {}).get("service_account_json")
            or config.get("service_account_json")
        )
        self._service_account: dict[str, Any] | None = None
        if raw_service_account:
            try:
                self._service_account = (
                    json.loads(raw_service_account)
                    if isinstance(raw_service_account, str)
                    else raw_service_account
                )
            except (TypeError, json.JSONDecodeError) as exc:
                raise ConnectorAuthError("Invalid Google service account JSON") from exc
        if not self._token and not self._api_key and not self._service_account:
            raise ConnectorAuthError(
                f"{self.service_slug} requires an OAuth token, API key, or service account"
            )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _url(self, path: str) -> str:
        return f"{self.base_url.rstrip('/')}/{path.lstrip('/')}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        await self._ensure_token()
        request_params = dict(params or {})
        if self._api_key:
            request_params["key"] = self._api_key
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            response = await client.request(
                method,
                self._url(path),
                headers=self._headers(),
                params=request_params,
                json=json,
            )
        if response.status_code == 401:
            raise ConnectorAuthError(f"{self.service_slug} access token is invalid or expired")
        response.raise_for_status()
        if not response.content:
            return {}
        data = response.json()
        return data if isinstance(data, dict) else {"items": data}

    async def _ensure_token(self) -> None:
        if self._token or not self._service_account:
            return
        email = self._service_account.get("client_email")
        private_key = self._service_account.get("private_key")
        if not email or not private_key:
            raise ConnectorAuthError("Google service account must include client_email and private_key")
        token_uri = self._service_account.get("token_uri", "https://oauth2.googleapis.com/token")
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT"}
        claims = {
            "iss": email,
            "scope": "https://www.googleapis.com/auth/cloud-platform",
            "aud": token_uri,
            "iat": now,
            "exp": now + 3600,
        }

        def encode(value: dict[str, Any]) -> str:
            raw = json.dumps(value, separators=(",", ":")).encode("utf-8")
            return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

        unsigned = f"{encode(header)}.{encode(claims)}".encode("ascii")
        try:
            key = serialization.load_pem_private_key(private_key.encode("utf-8"), password=None)
            signature = key.sign(unsigned, padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            raise ConnectorAuthError("Invalid Google service account private key") from exc
        assertion = f"{unsigned.decode('ascii')}.{base64.urlsafe_b64encode(signature).decode('ascii').rstrip('=')}"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                token_uri,
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                    "assertion": assertion,
                },
            )
        if response.status_code != 200:
            raise ConnectorAuthError(f"Google service account token exchange failed: {response.text}")
        token = response.json().get("access_token")
        if not token:
            raise ConnectorAuthError("Google service account token response did not include access_token")
        self._token = token

    def _missing(self, key: str) -> dict[str, Any] | None:
        value = self.config.get(key)
        if value:
            return None
        return {"items": [], "total": 0, "error": f"Missing required configuration: {key}"}

    async def connect(self) -> dict[str, Any]:
        result = await self.test()
        self._status = {
            "status": "connected" if result.get("success") else "error",
            "message": result.get("message", ""),
        }
        return self._status

    async def test(self) -> dict[str, Any]:
        try:
            result = await self._test_request()
            if result.get("configured") is False:
                return {
                    "success": False,
                    "message": result.get("error", "Integration is not configured"),
                }
            return {"success": True, "message": f"{self.service_slug} connection successful"}
        except Exception as exc:
            return {"success": False, "message": str(exc)}

    async def _test_request(self) -> dict[str, Any]:
        return await self._request("GET", self.discover_path(), params=self.discover_params())

    def discover_path(self) -> str:
        return "/"

    def discover_params(self) -> dict[str, Any]:
        return {}

    async def discover(self) -> dict[str, Any]:
        try:
            data = await self._request(
                "GET", self.discover_path(), params=self.discover_params()
            )
            items = self._items(data)
            return {"items": items, "total": len(items)}
        except Exception as exc:
            return {"items": [], "total": 0, "error": str(exc)}

    @staticmethod
    def _items(data: dict[str, Any]) -> list[dict[str, Any]]:
        for key in ("items", "connections", "spaces", "conferenceRecords", "files", "datasets", "buckets", "documents", "alertPolicies", "properties"):
            value = data.get(key)
            if isinstance(value, list):
                return [item if isinstance(item, dict) else {"value": item} for item in value]
        return [data] if data else []

    async def sync(self, options: dict | None = None) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        started_at = utcnow().isoformat()
        self._status = {"status": "running", "progress": 0, "started_at": started_at}
        discovered = await self.discover()
        if discovered.get("error"):
            self._status = {"status": "error", "progress": 0, "message": discovered["error"]}
            return {
                "job_id": job_id,
                "status": "failed",
                "started_at": started_at,
                "error": discovered["error"],
            }
        items = discovered.get("items", [])
        self._status = {
            "status": "completed",
            "progress": 100,
            "items_synced": len(items),
        }
        return {
            "job_id": job_id,
            "status": "completed",
            "started_at": started_at,
            "items": items,
            "total": len(items),
        }

    async def get_status(self) -> dict[str, Any]:
        return self._status

    async def disconnect(self) -> dict[str, Any]:
        self._status = {"status": "idle", "progress": 0, "message": "Disconnected"}
        return self._status

    async def refresh(self) -> dict[str, Any]:
        result = await self.test()
        return {
            "success": bool(result.get("success")),
            "message": result.get("message", "Google credentials refreshed"),
        }

    def validate(self) -> dict[str, Any]:
        errors: list[str] = []
        if not self._token and not self._api_key and not self._service_account:
            errors.append("Missing Google OAuth access token, API key, or service account")
        return {"valid": not errors, "errors": errors}

    def watch(self, poll_interval: int = 180) -> Any:
        return None


class GooglePeopleConnector(GoogleApiConnector):
    service_slug = "google_people"

    def discover_path(self) -> str:
        return "/v1/people/me/connections"

    def discover_params(self) -> dict[str, Any]:
        return {
            "pageSize": self.config.get("page_size", 100),
            "personFields": "names,emailAddresses,organizations,phoneNumbers",
        }


class GoogleSheetsConnector(GoogleApiConnector):
    service_slug = "google_sheets"
    base_url = "https://sheets.googleapis.com"

    def discover_path(self) -> str:
        spreadsheet_id = self.config.get("spreadsheet_id")
        if not spreadsheet_id:
            return "/v4/spreadsheets"
        return f"/v4/spreadsheets/{quote(str(spreadsheet_id), safe='')}"

    def discover_params(self) -> dict[str, Any]:
        return {"includeGridData": "false"}

    async def _test_request(self) -> dict[str, Any]:
        missing = self._missing("spreadsheet_id")
        if missing:
            return {"configured": False, **missing}
        return await super()._test_request()

    async def discover(self) -> dict[str, Any]:
        missing = self._missing("spreadsheet_id")
        if missing:
            return missing
        return await super().discover()


class GoogleDocsConnector(GoogleApiConnector):
    service_slug = "google_docs"
    base_url = "https://docs.googleapis.com"

    def discover_path(self) -> str:
        document_id = self.config.get("document_id")
        if not document_id:
            return "/v1/documents"
        return f"/v1/documents/{quote(str(document_id), safe='')}"

    async def _test_request(self) -> dict[str, Any]:
        missing = self._missing("document_id")
        if missing:
            return {"configured": False, **missing}
        return await super()._test_request()

    async def discover(self) -> dict[str, Any]:
        missing = self._missing("document_id")
        if missing:
            return missing
        return await super().discover()


class GoogleChatConnector(GoogleApiConnector):
    service_slug = "google_chat"
    base_url = "https://chat.googleapis.com"

    def discover_path(self) -> str:
        return "/v1/spaces"

    def discover_params(self) -> dict[str, Any]:
        return {"pageSize": self.config.get("page_size", 100)}


class GoogleMeetConnector(GoogleApiConnector):
    service_slug = "google_meet"
    base_url = "https://meet.googleapis.com"

    def discover_path(self) -> str:
        return "/v2/conferenceRecords"

    def discover_params(self) -> dict[str, Any]:
        return {"pageSize": self.config.get("page_size", 100)}


class GoogleFormsConnector(GoogleApiConnector):
    service_slug = "google_forms"
    base_url = "https://forms.googleapis.com"

    def discover_path(self) -> str:
        form_id = self.config.get("form_id")
        if not form_id:
            return "/v1/forms"
        return f"/v1/forms/{quote(str(form_id), safe='')}"

    async def _test_request(self) -> dict[str, Any]:
        missing = self._missing("form_id")
        if missing:
            return {"configured": False, **missing}
        return await super()._test_request()

    async def discover(self) -> dict[str, Any]:
        missing = self._missing("form_id")
        if missing:
            return missing
        return await super().discover()


class BigQueryConnector(GoogleApiConnector):
    service_slug = "bigquery"
    base_url = "https://bigquery.googleapis.com"

    def discover_path(self) -> str:
        project_id = self.config.get("project_id")
        if not project_id:
            return "/bigquery/v2/projects"
        return f"/bigquery/v2/projects/{quote(str(project_id), safe='')}/datasets"

    def discover_params(self) -> dict[str, Any]:
        return {"maxResults": self.config.get("page_size", 100)}


class GoogleCloudStorageConnector(GoogleApiConnector):
    service_slug = "google_cloud_storage"
    base_url = "https://storage.googleapis.com"

    def discover_path(self) -> str:
        bucket = self.config.get("bucket")
        if bucket:
            return f"/storage/v1/b/{quote(str(bucket), safe='')}/o"
        return "/storage/v1/b"

    def discover_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"maxResults": self.config.get("page_size", 100)}
        if self.config.get("project_id"):
            params["project"] = self.config["project_id"]
        if self.config.get("prefix"):
            params["prefix"] = self.config["prefix"]
        return params


class FirestoreConnector(GoogleApiConnector):
    service_slug = "firestore"
    base_url = "https://firestore.googleapis.com"

    def discover_path(self) -> str:
        project_id = self.config.get("project_id")
        database_id = self.config.get("database_id", "(default)")
        if not project_id:
            return "/v1/projects"
        path = f"/v1/projects/{quote(str(project_id), safe='')}/databases/{quote(str(database_id), safe='')}/documents"
        collection_id = self.config.get("collection_id")
        if collection_id:
            path += f"/{quote(str(collection_id), safe='')}"
        return path

    def _missing_project(self) -> dict[str, Any] | None:
        return self._missing("project_id")

    async def _test_request(self) -> dict[str, Any]:
        missing = self._missing_project()
        if missing:
            return {"configured": False, **missing}
        return await super()._test_request()


class GoogleAnalyticsConnector(GoogleApiConnector):
    service_slug = "google_analytics"
    base_url = "https://analyticsdata.googleapis.com"

    def discover_path(self) -> str:
        property_id = self.config.get("property_id")
        if not property_id:
            return "/v1beta/properties"
        return f"/v1beta/properties/{quote(str(property_id), safe='')}/metadata"

    async def _test_request(self) -> dict[str, Any]:
        missing = self._missing("property_id")
        if missing:
            return {"configured": False, **missing}
        return await super()._test_request()


class GoogleLoggingConnector(GoogleApiConnector):
    service_slug = "google_logging"
    base_url = "https://logging.googleapis.com"

    def discover_path(self) -> str:
        return "/v2/entries:list"

    async def _list_entries(self) -> dict[str, Any]:
        project_id = self.config.get("project_id")
        if not project_id:
            return {"items": [], "total": 0, "error": "Missing required configuration: project_id"}
        body = {
            "resourceNames": [f"projects/{project_id}"],
            "pageSize": self.config.get("page_size", 100),
            "orderBy": "timestamp desc",
        }
        if self.config.get("filter"):
            body["filter"] = self.config["filter"]
        return await self._request("POST", self.discover_path(), json=body)

    async def _test_request(self) -> dict[str, Any]:
        return await self._list_entries()

    async def discover(self) -> dict[str, Any]:
        try:
            data = await self._list_entries()
            items = self._items(data)
            return {"items": items, "total": len(items)}
        except Exception as exc:
            return {"items": [], "total": 0, "error": str(exc)}


class GoogleMonitoringConnector(GoogleApiConnector):
    service_slug = "google_monitoring"
    base_url = "https://monitoring.googleapis.com"

    def discover_path(self) -> str:
        project_id = self.config.get("project_id")
        if not project_id:
            return "/v3/projects"
        return f"/v3/projects/{quote(str(project_id), safe='')}/alertPolicies"

    def discover_params(self) -> dict[str, Any]:
        return {"pageSize": self.config.get("page_size", 100)}

    async def _test_request(self) -> dict[str, Any]:
        missing = self._missing("project_id")
        if missing:
            return {"configured": False, **missing}
        return await super()._test_request()


registry.register("google_people", GooglePeopleConnector)
registry.register("google_sheets", GoogleSheetsConnector)
registry.register("google_docs", GoogleDocsConnector)
registry.register("google_chat", GoogleChatConnector)
registry.register("google_meet", GoogleMeetConnector)
registry.register("google_forms", GoogleFormsConnector)
registry.register("bigquery", BigQueryConnector)
registry.register("google_cloud_storage", GoogleCloudStorageConnector)
registry.register("firestore", FirestoreConnector)
registry.register("google_analytics", GoogleAnalyticsConnector)
registry.register("google_logging", GoogleLoggingConnector)
registry.register("google_monitoring", GoogleMonitoringConnector)

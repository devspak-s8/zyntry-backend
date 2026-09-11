from __future__ import annotations

import base64
import hashlib
import secrets
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core.config import settings
from app.services.integrations.definitions import IntegrationDefinition


def generate_code_challenge(code_verifier: str) -> str:
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


class OAuth2AuthProvider:
    def generate_auth_flow(
        self,
        integration: IntegrationDefinition,
        redirect_uri: str,
        scope_override: list[str] | None = None,
        client_id: str | None = None,
        auth_url_override: str | None = None,
        extra_params: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        state = secrets.token_urlsafe(32)
        code_verifier = secrets.token_urlsafe(64)
        code_challenge = generate_code_challenge(code_verifier)

        scopes = scope_override or integration.required_scopes
        scope_str = " ".join(scopes)

        cid = client_id or self._client_id(integration)
        if not cid:
            raise ValueError(
                f"OAuth client ID is not configured for integration '{integration.slug}'."
            )
        auth_url = auth_url_override or self._default_auth_url(integration.slug)

        params: dict[str, Any] = {
            "client_id": cid,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        if scope_str:
            params["scope"] = scope_str
        if extra_params:
            params.update(extra_params)

        url = f"{auth_url}?{urlencode(params)}"
        return {
            "url": url,
            "state": state,
            "code_verifier": code_verifier,
        }

    async def exchange_code(
        self,
        integration: IntegrationDefinition,
        code: str,
        redirect_uri: str,
        code_verifier: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        token_url_override: str | None = None,
    ) -> dict[str, Any]:
        cid = client_id or self._client_id(integration)
        csecret = client_secret or self._client_secret(integration)
        if not cid:
            raise ValueError(
                f"OAuth client ID is not configured for integration '{integration.slug}'."
            )
        token_url = token_url_override or self._default_token_url(integration.slug)

        payload: dict[str, Any] = {
            "grant_type": "authorization_code",
            "client_id": cid,
            "code": code,
            "redirect_uri": redirect_uri,
        }
        if csecret:
            payload["client_secret"] = csecret
        if code_verifier:
            payload["code_verifier"] = code_verifier

        # Allow offline / mock exchange in testing or missing external server
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                headers = {"Accept": "application/json"}
                resp = await client.post(token_url, data=payload, headers=headers)
                if resp.status_code != 200:
                    raise ValueError(
                        f"OAuth token exchange failed for '{integration.slug}' "
                        f"with provider status {resp.status_code}."
                    )
                data = resp.json()
                access_token = data.get("access_token") or data.get("token")
                if not access_token:
                    raise ValueError(
                        f"OAuth token exchange for '{integration.slug}' returned no access token."
                    )
                return {
                    "access_token": access_token,
                    "refresh_token": data.get("refresh_token"),
                    "expires_in": data.get("expires_in"),
                    "scope": data.get("scope") or " ".join(integration.required_scopes),
                    "token_type": data.get("token_type", "Bearer"),
                }
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(
                f"OAuth token exchange could not reach '{integration.slug}' provider."
            ) from exc

    @staticmethod
    def _client_id(integration: IntegrationDefinition) -> str:
        aliases = {
            "microsoft_teams": "MICROSOFT",
        }
        setting_prefix = aliases.get(integration.slug, integration.slug.upper())
        explicit = getattr(settings, f"{setting_prefix}_CLIENT_ID", "")
        if explicit:
            return explicit
        if integration.slug.startswith("google_") or integration.slug in {
            "gmail", "bigquery", "firestore",
        }:
            return settings.GOOGLE_CLIENT_ID
        return ""

    @staticmethod
    def _client_secret(integration: IntegrationDefinition) -> str:
        aliases = {
            "microsoft_teams": "MICROSOFT",
        }
        setting_prefix = aliases.get(integration.slug, integration.slug.upper())
        explicit = getattr(settings, f"{setting_prefix}_CLIENT_SECRET", "")
        if explicit:
            return explicit
        if integration.slug.startswith("google_") or integration.slug in {
            "gmail", "bigquery", "firestore",
        }:
            return settings.GOOGLE_CLIENT_SECRET
        return ""

    def _default_auth_url(self, slug: str) -> str:
        urls = {
            "github": "https://github.com/login/oauth/authorize",
            "gitlab": "https://gitlab.com/oauth/authorize",
            "bitbucket": "https://bitbucket.org/site/oauth2/authorize",
            "slack": "https://slack.com/oauth/v2/authorize",
            "discord": "https://discord.com/oauth2/authorize",
            "microsoft_teams": (
                "https://login.microsoftonline.com/"
                f"{getattr(settings, 'MICROSOFT_TENANT_ID', 'common') or 'common'}"
                "/oauth2/v2.0/authorize"
            ),
            "notion": "https://api.notion.com/v1/oauth/authorize",
            "jira": "https://auth.atlassian.com/authorize",
            "confluence": "https://auth.atlassian.com/authorize",
            "arcgis": "https://www.arcgis.com/sharing/rest/oauth2/authorize",
            "gmail": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_drive": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_calendar": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_people": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_sheets": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_docs": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_chat": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_meet": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_forms": "https://accounts.google.com/o/oauth2/v2/auth",
            "bigquery": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_cloud_storage": "https://accounts.google.com/o/oauth2/v2/auth",
            "firestore": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_analytics": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_logging": "https://accounts.google.com/o/oauth2/v2/auth",
            "google_monitoring": "https://accounts.google.com/o/oauth2/v2/auth",
        }
        try:
            return urls[slug]
        except KeyError as exc:
            raise ValueError(
                f"OAuth authorization is not configured for integration '{slug}'."
            ) from exc

    def _default_token_url(self, slug: str) -> str:
        urls = {
            "github": "https://github.com/login/oauth/access_token",
            "gitlab": "https://gitlab.com/oauth/token",
            "bitbucket": "https://bitbucket.org/site/oauth2/access_token",
            "slack": "https://slack.com/api/oauth.v2.access",
            "discord": "https://discord.com/api/oauth2/token",
            "microsoft_teams": (
                "https://login.microsoftonline.com/"
                f"{getattr(settings, 'MICROSOFT_TENANT_ID', 'common') or 'common'}"
                "/oauth2/v2.0/token"
            ),
            "notion": "https://api.notion.com/v1/oauth/token",
            "jira": "https://auth.atlassian.com/oauth/token",
            "confluence": "https://auth.atlassian.com/oauth/token",
            "arcgis": "https://www.arcgis.com/sharing/rest/oauth2/token",
            "gmail": "https://oauth2.googleapis.com/token",
            "google_drive": "https://oauth2.googleapis.com/token",
            "google_calendar": "https://oauth2.googleapis.com/token",
            "google_people": "https://oauth2.googleapis.com/token",
            "google_sheets": "https://oauth2.googleapis.com/token",
            "google_docs": "https://oauth2.googleapis.com/token",
            "google_chat": "https://oauth2.googleapis.com/token",
            "google_meet": "https://oauth2.googleapis.com/token",
            "google_forms": "https://oauth2.googleapis.com/token",
            "bigquery": "https://oauth2.googleapis.com/token",
            "google_cloud_storage": "https://oauth2.googleapis.com/token",
            "firestore": "https://oauth2.googleapis.com/token",
            "google_analytics": "https://oauth2.googleapis.com/token",
            "google_logging": "https://oauth2.googleapis.com/token",
            "google_monitoring": "https://oauth2.googleapis.com/token",
        }
        try:
            return urls[slug]
        except KeyError as exc:
            raise ValueError(
                f"OAuth token exchange is not configured for integration '{slug}'."
            ) from exc


class GitHubAuthProvider(OAuth2AuthProvider):
    """Specialized GitHub provider supporting user OAuth and GitHub App installations."""

    def generate_installation_url(self, app_slug: str, state: str) -> str:
        return f"https://github.com/apps/{app_slug}/installations/new?state={state}"


default_oauth_provider = OAuth2AuthProvider()
default_github_provider = GitHubAuthProvider()

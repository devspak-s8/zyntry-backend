from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.oauth import OAuthProvider
from app.services.oauth.service import OAuthService


_PROVIDERS = {
    "github": {
        "display_name": "GitHub",
        "client_id": "GITHUB_CLIENT_ID",
        "client_secret": "GITHUB_CLIENT_SECRET",
        "auth_url": "https://github.com/login/oauth/authorize",
        "token_url": "https://github.com/login/oauth/access_token",
        "scopes": ["repo", "read:user", "user:email"],
    },
    "notion": {
        "display_name": "Notion",
        "client_id": "NOTION_CLIENT_ID",
        "client_secret": "NOTION_CLIENT_SECRET",
        "auth_url": "https://api.notion.com/v1/oauth/authorize",
        "token_url": "https://api.notion.com/v1/oauth/token",
        "scopes": [],
    },
    "slack": {
        "display_name": "Slack",
        "client_id": "SLACK_CLIENT_ID",
        "client_secret": "SLACK_CLIENT_SECRET",
        "auth_url": "https://slack.com/oauth/v2/authorize",
        "token_url": "https://slack.com/api/oauth.v2.access",
        "scopes": ["channels:read", "channels:history", "users:read"],
    },
}


async def seed_oauth_tool_providers(db: AsyncSession) -> None:
    for name, definition in _PROVIDERS.items():
        client_id = getattr(settings, definition["client_id"])
        client_secret = getattr(settings, definition["client_secret"])
        if not client_id or not client_secret:
            continue
        result = await db.execute(select(OAuthProvider).where(OAuthProvider.name == name))
        provider = result.scalar_one_or_none()
        values = {
            "display_name": definition["display_name"],
            "client_id": client_id,
            "client_secret_encrypted": OAuthService._encrypt(client_secret),
            "auth_url": definition["auth_url"],
            "token_url": definition["token_url"],
            "scopes": definition["scopes"],
            "is_enabled": True,
        }
        if provider is None:
            db.add(OAuthProvider(name=name, **values))
        else:
            for field, value in values.items():
                setattr(provider, field, value)
    await db.commit()

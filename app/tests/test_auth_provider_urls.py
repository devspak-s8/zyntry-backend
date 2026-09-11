from __future__ import annotations

import pytest

from app.services.integrations.auth_providers import OAuth2AuthProvider


@pytest.mark.parametrize(
    ("slug", "expected_authorize", "expected_token"),
    [
        ("github", "github.com/login/oauth/authorize", "github.com/login/oauth/access_token"),
        ("gitlab", "gitlab.com/oauth/authorize", "gitlab.com/oauth/token"),
        ("bitbucket", "bitbucket.org/site/oauth2/authorize", "bitbucket.org/site/oauth2/access_token"),
        ("discord", "discord.com/oauth2/authorize", "discord.com/api/oauth2/token"),
        ("jira", "auth.atlassian.com/authorize", "auth.atlassian.com/oauth/token"),
        ("arcgis", "www.arcgis.com/sharing/rest/oauth2/authorize", "www.arcgis.com/sharing/rest/oauth2/token"),
    ],
)
def test_supported_oauth_integrations_use_real_provider_endpoints(
    slug: str, expected_authorize: str, expected_token: str
) -> None:
    provider = OAuth2AuthProvider()
    assert expected_authorize in provider._default_auth_url(slug)
    assert expected_token in provider._default_token_url(slug)


def test_unknown_oauth_integration_does_not_return_dead_auth_subdomain() -> None:
    provider = OAuth2AuthProvider()
    with pytest.raises(ValueError, match="OAuth authorization is not configured"):
        provider._default_auth_url("unknown_oauth_provider")


def test_google_integrations_use_google_oauth_endpoint() -> None:
    provider = OAuth2AuthProvider()
    for slug in ("google_drive", "google_people", "google_sheets"):
        assert provider._default_auth_url(slug).startswith(
            "https://accounts.google.com/o/oauth2/v2/auth"
        )
        assert provider._default_token_url(slug) == "https://oauth2.googleapis.com/token"


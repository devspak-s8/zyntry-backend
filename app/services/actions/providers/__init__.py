from __future__ import annotations

from app.services.actions.providers.box import BoxActionProvider, OneDriveActionProvider
from app.services.actions.providers.confluence import ConfluenceActionProvider
from app.services.actions.providers.github import GitHubActionProvider
from app.services.actions.providers.gitlab import GitLabActionProvider
from app.services.actions.providers.gmail import GmailActionProvider
from app.services.actions.providers.google_drive import GoogleDriveActionProvider
from app.services.actions.providers.jira import JiraActionProvider
from app.services.actions.providers.notion import NotionActionProvider
from app.services.actions.providers.slack import SlackActionProvider
from app.services.actions.registry import ActionRegistry

providers = [
    GitHubActionProvider,
    GmailActionProvider,
    NotionActionProvider,
    SlackActionProvider,
    JiraActionProvider,
    GitLabActionProvider,
    GoogleDriveActionProvider,
    ConfluenceActionProvider,
    BoxActionProvider,
    OneDriveActionProvider,
]

for provider_cls in providers:
    ActionRegistry.register(provider_cls())

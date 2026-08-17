from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class IntegrationCapability:
    slug: str
    name: str
    description: str
    is_write: bool = False
    required_scopes: list[str] = field(default_factory=list)
    permission_requirements: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class IntegrationDefinition:
    id: str
    slug: str
    name: str
    description: str
    category: str
    icon: str = ""
    enabled: bool = True
    supported_connection_modes: list[str] = field(
        default_factory=lambda: ["zyntry_managed", "end_user_oauth"]
    )
    authentication_methods: list[str] = field(default_factory=lambda: ["oauth2"])
    capabilities: list[IntegrationCapability] = field(default_factory=list)
    required_scopes: list[str] = field(default_factory=list)
    documentation_url: str = ""
    configuration_schema: dict[str, Any] = field(default_factory=dict)
    credential_requirements: dict[str, Any] = field(default_factory=dict)
    health_check: dict[str, Any] = field(default_factory=lambda: {"type": "ping", "interval_seconds": 300})
    version: str = "1.0.0"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = [c.to_dict() for c in self.capabilities]
        return data


# Canonical Integration Definitions Catalog
DEFINITIONS: dict[str, IntegrationDefinition] = {
    "github": IntegrationDefinition(
        id="int_github",
        slug="github",
        name="GitHub",
        description="Connect repositories, files, issues, commits, pull requests, and code search.",
        category="development",
        icon="github",
        enabled=True,
        supported_connection_modes=["zyntry_managed", "end_user_oauth", "api_key"],
        authentication_methods=["oauth2", "github_app", "personal_access_token"],
        capabilities=[
            IntegrationCapability(
                slug="repository_search",
                name="Repository Search",
                description="Search repositories across public and private repositories.",
                is_write=False,
                required_scopes=["repo", "read:org"],
            ),
            IntegrationCapability(
                slug="file_retrieval",
                name="File Retrieval",
                description="Read contents and trees of repository files and directories.",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="issue_access",
                name="Issue Access",
                description="List, read, search, and comment on issues.",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="pull_requests",
                name="Pull Requests",
                description="Read and analyze pull request diffs, reviews, and comments.",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="commits",
                name="Commits & History",
                description="Inspect commit logs, authors, and file changes.",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="repository_metadata",
                name="Repository Metadata",
                description="Read repository settings, branches, tags, and languages.",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="write_actions",
                name="Write Actions",
                description="Create issues, submit reviews, or commit changes where explicitly authorized.",
                is_write=True,
                required_scopes=["repo", "workflow"],
                permission_requirements=["admin", "write"],
            ),
        ],
        required_scopes=["repo", "read:org", "read:user"],
        documentation_url="https://docs.zyntry.space/integrations/github",
        configuration_schema={
            "type": "object",
            "properties": {
                "organization": {"type": "string", "description": "Optional GitHub organization filter"},
                "repositories": {"type": "array", "items": {"type": "string"}, "description": "Optional repository filter whitelist"},
            },
        },
        credential_requirements={
            "oauth2": {"client_id": "string", "client_secret": "string"},
            "personal_access_token": {"token": "string"},
        },
    ),
    "slack": IntegrationDefinition(
        id="int_slack",
        slug="slack",
        name="Slack",
        description="Search messages, list channels, monitor discussions, and send notifications.",
        category="communication",
        icon="slack",
        enabled=True,
        supported_connection_modes=["zyntry_managed", "end_user_oauth", "api_key"],
        authentication_methods=["oauth2", "bot_token"],
        capabilities=[
            IntegrationCapability(
                slug="message_search",
                name="Message Search",
                description="Search messages across channels and threads.",
                is_write=False,
                required_scopes=["channels:history", "groups:history"],
            ),
            IntegrationCapability(
                slug="conversation_retrieval",
                name="Conversation Retrieval",
                description="Retrieve active thread conversations and message histories.",
                is_write=False,
                required_scopes=["channels:read", "groups:read"],
            ),
            IntegrationCapability(
                slug="channel_info",
                name="Channel Information",
                description="List public and private channels and members.",
                is_write=False,
                required_scopes=["channels:read"],
            ),
            IntegrationCapability(
                slug="send_messages",
                name="Send Messages",
                description="Post notifications, summaries, and responses into channels.",
                is_write=True,
                required_scopes=["chat:write"],
            ),
        ],
        required_scopes=["channels:read", "channels:history", "chat:write"],
        documentation_url="https://docs.zyntry.space/integrations/slack",
    ),
    "notion": IntegrationDefinition(
        id="int_notion",
        slug="notion",
        name="Notion",
        description="Search pages, index knowledge databases, retrieve blocks, and create pages.",
        category="knowledge",
        icon="notion",
        enabled=True,
        supported_connection_modes=["zyntry_managed", "end_user_oauth", "api_key"],
        authentication_methods=["oauth2", "internal_integration_token"],
        capabilities=[
            IntegrationCapability(
                slug="search_pages",
                name="Search Pages",
                description="Search workspace pages and titles.",
                is_write=False,
            ),
            IntegrationCapability(
                slug="retrieve_pages",
                name="Retrieve Content",
                description="Fetch page blocks, markdown, and properties.",
                is_write=False,
            ),
            IntegrationCapability(
                slug="create_update_pages",
                name="Create & Update Pages",
                description="Append blocks or create new pages in authorized databases.",
                is_write=True,
            ),
        ],
        required_scopes=[],
        documentation_url="https://docs.zyntry.space/integrations/notion",
    ),
    "postgres": IntegrationDefinition(
        id="int_postgres",
        slug="postgres",
        name="PostgreSQL",
        description="Execute read-only SQL queries, inspect table schemas, and retrieve structured rows.",
        category="database",
        icon="postgresql",
        enabled=True,
        supported_connection_modes=["zyntry_managed", "database_credentials"],
        authentication_methods=["connection_string", "credentials"],
        capabilities=[
            IntegrationCapability(
                slug="query",
                name="Query Execution",
                description="Execute structured SELECT queries with limit guardrails.",
                is_write=False,
            ),
            IntegrationCapability(
                slug="schema_inspection",
                name="Schema Inspection",
                description="Inspect tables, columns, indexes, and relations.",
                is_write=False,
            ),
            IntegrationCapability(
                slug="structured_retrieval",
                name="Structured Retrieval",
                description="Retrieve filtered records for contextual RAG grounding.",
                is_write=False,
            ),
        ],
        required_scopes=[],
        documentation_url="https://docs.zyntry.space/integrations/postgres",
        credential_requirements={
            "connection_string": {"url": "string"},
            "credentials": {"host": "string", "port": "integer", "database": "string", "username": "string", "password": "string"},
        },
    ),
    "mongodb": IntegrationDefinition(
        id="int_mongodb",
        slug="mongodb",
        name="MongoDB",
        description="Query collections, inspect document schemas, and retrieve JSON records.",
        category="database",
        icon="mongodb",
        enabled=True,
        supported_connection_modes=["zyntry_managed", "database_credentials"],
        authentication_methods=["connection_string"],
        capabilities=[
            IntegrationCapability(
                slug="collection_querying",
                name="Collection Querying",
                description="Find documents using MongoDB filter expressions.",
                is_write=False,
            ),
            IntegrationCapability(
                slug="document_retrieval",
                name="Document Retrieval",
                description="Fetch specific documents by ID or attributes.",
                is_write=False,
            ),
        ],
        required_scopes=[],
        documentation_url="https://docs.zyntry.space/integrations/mongodb",
    ),
    "gmail": IntegrationDefinition(
        id="int_gmail",
        slug="gmail",
        name="Gmail",
        description="Search emails, read message threads, and compose draft replies.",
        category="communication",
        icon="gmail",
        enabled=True,
        supported_connection_modes=["zyntry_managed", "end_user_oauth"],
        authentication_methods=["oauth2"],
        capabilities=[
            IntegrationCapability(
                slug="search_messages",
                name="Search Messages",
                description="Search emails by sender, subject, date, and query.",
                is_write=False,
                required_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            ),
            IntegrationCapability(
                slug="read_threads",
                name="Read Threads",
                description="Retrieve full email threads with attachments metadata.",
                is_write=False,
                required_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
            ),
            IntegrationCapability(
                slug="create_drafts",
                name="Create Drafts",
                description="Create draft email replies without sending.",
                is_write=True,
                required_scopes=["https://www.googleapis.com/auth/gmail.compose"],
            ),
        ],
        required_scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        documentation_url="https://docs.zyntry.space/integrations/gmail",
    ),
    "s3": IntegrationDefinition(
        id="int_s3",
        slug="s3",
        name="Amazon S3",
        description="Connect Amazon S3 buckets for document extraction and retrieval.",
        category="storage",
        icon="s3",
        enabled=True,
        supported_connection_modes=["zyntry_managed", "api_key"],
        authentication_methods=["service_account", "api_key"],
        capabilities=[
            IntegrationCapability(
                slug="object_retrieval",
                name="Object Retrieval",
                description="Fetch documents and objects from S3 buckets.",
                is_write=False,
            ),
            IntegrationCapability(
                slug="bucket_listing",
                name="Bucket Listing",
                description="List bucket keys and metadata.",
                is_write=False,
            ),
        ],
        required_scopes=[],
        documentation_url="https://docs.zyntry.space/integrations/s3",
    ),
    "redis": IntegrationDefinition(
        id="int_redis",
        slug="redis",
        name="Redis",
        description="Connect Redis caches and key-value datastores.",
        category="database",
        icon="redis",
        enabled=True,
        supported_connection_modes=["zyntry_managed", "database_credentials"],
        authentication_methods=["connection_string"],
        capabilities=[
            IntegrationCapability(
                slug="key_retrieval",
                name="Key Retrieval",
                description="Get values and query keys.",
                is_write=False,
            ),
        ],
        required_scopes=[],
        documentation_url="https://docs.zyntry.space/integrations/redis",
    ),
    "website": IntegrationDefinition(
        id="int_website",
        slug="website",
        name="Website Web Crawler",
        description="Crawl and extract public website documentation and webpages.",
        category="web",
        icon="globe",
        enabled=True,
        supported_connection_modes=["zyntry_managed", "custom"],
        authentication_methods=["none", "api_key"],
        capabilities=[
            IntegrationCapability(
                slug="page_crawl",
                name="Page Crawl",
                description="Fetch and parse clean markdown from URL.",
                is_write=False,
            ),
        ],
        required_scopes=[],
        documentation_url="https://docs.zyntry.space/integrations/website",
    ),
    "mcp": IntegrationDefinition(
        id="int_mcp",
        slug="mcp",
        name="Model Context Protocol (MCP)",
        description="Connect tools and servers implementing the open Model Context Protocol.",
        category="api",
        icon="mcp",
        enabled=True,
        supported_connection_modes=["zyntry_managed", "api_key", "custom"],
        authentication_methods=["api_key", "bearer_token", "none"],
        capabilities=[
            IntegrationCapability(
                slug="tool_execution",
                name="Tool Execution",
                description="Invoke remote MCP server tools dynamically.",
                is_write=True,
            ),
            IntegrationCapability(
                slug="resource_reading",
                name="Resource Reading",
                description="Read MCP server resources and context.",
                is_write=False,
            ),
        ],
        required_scopes=[],
        documentation_url="https://docs.zyntry.space/integrations/mcp",
    ),
    "document_storage": IntegrationDefinition(
        id="int_document_storage",
        slug="document_storage",
        name="Uploaded Documents",
        description="Upload and index PDFs, Markdown, Word documents, and text files for RAG retrieval.",
        category="knowledge",
        icon="file-text",
        enabled=True,
        supported_connection_modes=["zyntry_managed"],
        authentication_methods=["none"],
        capabilities=[
            IntegrationCapability(
                slug="document_indexing",
                name="Document Indexing",
                description="Parse, chunk, and embed uploaded documents for vector search.",
                is_write=False,
            ),
            IntegrationCapability(
                slug="document_search",
                name="Document Search",
                description="Semantic search across indexed documents for RAG retrieval.",
                is_write=False,
            ),
            IntegrationCapability(
                slug="document_upload",
                name="Document Upload",
                description="Upload new documents (PDF, MD, DOCX, TXT) to the runtime knowledge base.",
                is_write=True,
            ),
        ],
        required_scopes=[],
        documentation_url="https://docs.zyntry.space/integrations/document-storage",
    ),
}


class IntegrationRegistry:
    def __init__(self, definitions: dict[str, IntegrationDefinition] | None = None) -> None:
        self._definitions: dict[str, IntegrationDefinition] = definitions or dict(DEFINITIONS)

    def register(self, definition: IntegrationDefinition) -> None:
        self._definitions[definition.slug] = definition

    def get(self, slug_or_id: str) -> IntegrationDefinition | None:
        if slug_or_id in self._definitions:
            return self._definitions[slug_or_id]
        for item in self._definitions.values():
            if item.id == slug_or_id:
                return item
        return None

    def list_all(self, category: str | None = None, enabled_only: bool = True) -> list[IntegrationDefinition]:
        items = list(self._definitions.values())
        if enabled_only:
            items = [i for i in items if i.enabled]
        if category:
            items = [i for i in items if i.category.lower() == category.lower()]
        return items

    def list_slugs(self) -> list[str]:
        return [i.slug for i in self.list_all()]


integration_registry = IntegrationRegistry()

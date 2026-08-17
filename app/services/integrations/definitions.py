from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class IntegrationCapability:
    slug: str
    name: str
    description: str
    operation: str = "read"  # "read", "write", "search", "execute", "manage"
    is_write: bool = False
    required_scopes: list[str] = field(default_factory=list)
    supported_connection_modes: list[str] = field(
        default_factory=lambda: ["zyntry_managed", "end_user_oauth"]
    )
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
    status: str = "available"  # "available", "beta", "coming_soon", "disabled", "deprecated"
    enabled: bool = True
    connection_modes: list[str] = field(
        default_factory=lambda: ["zyntry_managed", "end_user_oauth"]
    )
    auth_methods: list[str] = field(default_factory=lambda: ["oauth2"])
    capabilities: list[IntegrationCapability] = field(default_factory=list)
    scopes: list[str] = field(default_factory=list)
    documentation_url: str = ""
    configuration_schema: dict[str, Any] = field(default_factory=dict)
    credential_requirements: dict[str, Any] = field(default_factory=dict)
    health_check: dict[str, Any] = field(
        default_factory=lambda: {"type": "ping", "interval_seconds": 300}
    )
    version: str = "1.0.0"
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def supports_zyntry_managed(self) -> bool:
        return "zyntry_managed" in self.connection_modes

    @property
    def supports_end_user_oauth(self) -> bool:
        return "end_user_oauth" in self.connection_modes

    @property
    def supports_api_key(self) -> bool:
        return any(
            m in self.auth_methods
            for m in ["api_key", "personal_access_token", "bot_token", "token", "app_password"]
        )

    @property
    def supports_database_credentials(self) -> bool:
        return any(
            m in self.auth_methods
            for m in ["connection_string", "database_credentials", "storage_credentials"]
        )

    # Alias for backward compatibility
    @property
    def supported_connection_modes(self) -> list[str]:
        return self.connection_modes

    # Alias for backward compatibility
    @property
    def authentication_methods(self) -> list[str]:
        return self.auth_methods

    # Alias for backward compatibility
    @property
    def required_scopes(self) -> list[str]:
        return self.scopes

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities"] = [c.to_dict() for c in self.capabilities]
        data["supported_connection_modes"] = self.connection_modes
        data["authentication_methods"] = self.auth_methods
        data["required_scopes"] = self.scopes
        data["supports_zyntry_managed"] = self.supports_zyntry_managed
        data["supports_end_user_oauth"] = self.supports_end_user_oauth
        data["supports_api_key"] = self.supports_api_key
        data["supports_database_credentials"] = self.supports_database_credentials
        return data


# Canonical Integration Definitions Catalog
DEFINITIONS: dict[str, IntegrationDefinition] = {
    # -------------------------------------------------------------
    # 1. DEVELOPER / CODE
    # -------------------------------------------------------------
    "github": IntegrationDefinition(
        id="int_github",
        slug="github",
        name="GitHub",
        description="Connect repositories, file search, issue triage, commits, and pull requests.",
        category="developer",
        icon="github",
        status="available",
        connection_modes=["zyntry_managed", "end_user_oauth", "api_key"],
        auth_methods=["oauth2", "github_app", "personal_access_token"],
        scopes=["repo", "read:org", "read:user"],
        capabilities=[
            IntegrationCapability(
                slug="repository_search",
                name="Repository Search",
                description="Search code and repository contents.",
                operation="read",
                is_write=False,
                required_scopes=["repo", "read:org"],
            ),
            IntegrationCapability(
                slug="repository_metadata",
                name="Repository Metadata",
                description="Read repository settings, branches, tags, and languages.",
                operation="read",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="file_retrieval",
                name="File Retrieval",
                description="Read contents and trees of repository files.",
                operation="read",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="commits",
                name="Commits & History",
                description="Inspect commit logs, authors, and file diffs.",
                operation="read",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="issues",
                name="Issues",
                description="List, read, search, and comment on issues.",
                operation="read",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="issue_access",
                name="Issue Access",
                description="List, read, search, and comment on issues.",
                operation="read",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="pull_requests",
                name="Pull Requests",
                description="Read and analyze pull request diffs, reviews, and comments.",
                operation="read",
                is_write=False,
                required_scopes=["repo"],
            ),
            IntegrationCapability(
                slug="write_actions",
                name="Write Actions",
                description="Create branches, commit changes, and submit PRs or issue comments.",
                operation="write",
                is_write=True,
                required_scopes=["repo"],
            ),
        ],
    ),
    "gitlab": IntegrationDefinition(
        id="int_gitlab",
        slug="gitlab",
        name="GitLab",
        description="Access GitLab projects, merge requests, issues, and repository files.",
        category="developer",
        icon="gitlab",
        status="beta",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2", "personal_access_token"],
        scopes=["read_api", "read_repository"],
        capabilities=[
            IntegrationCapability(
                slug="repository_search",
                name="Repository Search",
                description="Search project repositories.",
                operation="read",
                is_write=False,
                required_scopes=["read_repository"],
            ),
            IntegrationCapability(
                slug="file_retrieval",
                name="File Retrieval",
                description="Fetch files from GitLab repositories.",
                operation="read",
                is_write=False,
                required_scopes=["read_repository"],
            ),
            IntegrationCapability(
                slug="issues",
                name="Issues",
                description="Read and triage GitLab project issues.",
                operation="read",
                is_write=False,
                required_scopes=["read_api"],
            ),
            IntegrationCapability(
                slug="merge_requests",
                name="Merge Requests",
                description="Inspect merge request diffs and discussions.",
                operation="read",
                is_write=False,
                required_scopes=["read_api"],
            ),
        ],
    ),
    "bitbucket": IntegrationDefinition(
        id="int_bitbucket",
        slug="bitbucket",
        name="Bitbucket",
        description="Bitbucket Cloud repositories, pull requests, and file search.",
        category="developer",
        icon="bitbucket",
        status="coming_soon",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2", "app_password"],
        scopes=["repository:read"],
        capabilities=[
            IntegrationCapability(
                slug="repository_search",
                name="Repository Search",
                description="Search Bitbucket repositories.",
                operation="read",
                is_write=False,
                required_scopes=["repository:read"],
            ),
            IntegrationCapability(
                slug="file_retrieval",
                name="File Retrieval",
                description="Retrieve file trees and contents.",
                operation="read",
                is_write=False,
                required_scopes=["repository:read"],
            ),
            IntegrationCapability(
                slug="pull_requests",
                name="Pull Requests",
                description="Read pull requests and comments.",
                operation="read",
                is_write=False,
                required_scopes=["repository:read"],
            ),
        ],
    ),

    # -------------------------------------------------------------
    # 2. COMMUNICATION
    # -------------------------------------------------------------
    "slack": IntegrationDefinition(
        id="int_slack",
        slug="slack",
        name="Slack",
        description="Search messages, read channel discussions, and post notifications.",
        category="communication",
        icon="slack",
        status="available",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2", "bot_token"],
        scopes=["channels:history", "channels:read", "chat:write", "search:read"],
        capabilities=[
            IntegrationCapability(
                slug="message_search",
                name="Message Search",
                description="Search messages and threads across channels.",
                operation="search",
                is_write=False,
                required_scopes=["search:read", "channels:history"],
            ),
            IntegrationCapability(
                slug="conversation_retrieval",
                name="Conversation Retrieval",
                description="Read full message thread history.",
                operation="read",
                is_write=False,
                required_scopes=["channels:history"],
            ),
            IntegrationCapability(
                slug="channel_info",
                name="Channel Information",
                description="List public and private channels and member metadata.",
                operation="read",
                is_write=False,
                required_scopes=["channels:read"],
            ),
            IntegrationCapability(
                slug="send_messages",
                name="Send Messages",
                description="Send updates and message responses to designated channels.",
                operation="write",
                is_write=True,
                required_scopes=["chat:write"],
            ),
        ],
    ),
    "discord": IntegrationDefinition(
        id="int_discord",
        slug="discord",
        name="Discord",
        description="Connect Discord guild channels, search chat history, and post alerts.",
        category="communication",
        icon="discord",
        status="beta",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2", "bot_token"],
        scopes=["bot", "messages.read"],
        capabilities=[
            IntegrationCapability(
                slug="message_history",
                name="Message History",
                description="Read guild and channel message logs.",
                operation="read",
                is_write=False,
                required_scopes=["messages.read"],
            ),
            IntegrationCapability(
                slug="channel_info",
                name="Channel Information",
                description="List guild channels and roles.",
                operation="read",
                is_write=False,
                required_scopes=["bot"],
            ),
            IntegrationCapability(
                slug="send_messages",
                name="Send Messages",
                description="Post notifications to Discord channels.",
                operation="write",
                is_write=True,
                required_scopes=["bot"],
            ),
        ],
    ),
    "microsoft_teams": IntegrationDefinition(
        id="int_microsoft_teams",
        slug="microsoft_teams",
        name="Microsoft Teams",
        description="Search Teams channel conversations and team chats via Microsoft Graph.",
        category="communication",
        icon="microsoft_teams",
        status="coming_soon",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2"],
        scopes=["ChannelMessage.Read.All", "Team.ReadBasic.All"],
        capabilities=[
            IntegrationCapability(
                slug="message_search",
                name="Message Search",
                description="Search team channel messages.",
                operation="search",
                is_write=False,
                required_scopes=["ChannelMessage.Read.All"],
            ),
            IntegrationCapability(
                slug="channel_info",
                name="Channel Information",
                description="List teams and channel directories.",
                operation="read",
                is_write=False,
                required_scopes=["Team.ReadBasic.All"],
            ),
        ],
    ),

    # -------------------------------------------------------------
    # 3. PRODUCTIVITY / KNOWLEDGE
    # -------------------------------------------------------------
    "notion": IntegrationDefinition(
        id="int_notion",
        slug="notion",
        name="Notion",
        description="Search pages, index knowledge databases, and read structured wiki blocks.",
        category="productivity",
        icon="notion",
        status="available",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2", "internal_integration_token"],
        scopes=["read_content", "update_content", "insert_content"],
        capabilities=[
            IntegrationCapability(
                slug="search_pages",
                name="Search Pages",
                description="Search workspace pages and databases by title and content.",
                operation="search",
                is_write=False,
                required_scopes=["read_content"],
            ),
            IntegrationCapability(
                slug="retrieve_pages",
                name="Retrieve Pages",
                description="Read full Markdown block trees of Notion pages.",
                operation="read",
                is_write=False,
                required_scopes=["read_content"],
            ),
            IntegrationCapability(
                slug="create_pages",
                name="Create Pages",
                description="Create new documentation and database entries.",
                operation="write",
                is_write=True,
                required_scopes=["insert_content"],
            ),
            IntegrationCapability(
                slug="update_pages",
                name="Update Pages",
                description="Append or modify blocks within Notion pages.",
                operation="write",
                is_write=True,
                required_scopes=["update_content"],
            ),
        ],
    ),
    "jira": IntegrationDefinition(
        id="int_jira",
        slug="jira",
        name="Jira",
        description="Search Jira tickets, sprint backlogs, and issue statuses.",
        category="productivity",
        icon="jira",
        status="beta",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2", "api_token"],
        scopes=["read:jira-work", "read:jira-user"],
        capabilities=[
            IntegrationCapability(
                slug="issue_search",
                name="Issue Search",
                description="Search Jira issues using JQL queries.",
                operation="search",
                is_write=False,
                required_scopes=["read:jira-work"],
            ),
            IntegrationCapability(
                slug="issue_retrieval",
                name="Issue Retrieval",
                description="Fetch ticket descriptions, comments, and attachments.",
                operation="read",
                is_write=False,
                required_scopes=["read:jira-work"],
            ),
            IntegrationCapability(
                slug="project_metadata",
                name="Project Metadata",
                description="List projects, boards, components, and issue types.",
                operation="read",
                is_write=False,
                required_scopes=["read:jira-work"],
            ),
        ],
    ),
    "confluence": IntegrationDefinition(
        id="int_confluence",
        slug="confluence",
        name="Confluence",
        description="Index Confluence spaces and retrieve technical documentation.",
        category="productivity",
        icon="confluence",
        status="beta",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2", "api_token"],
        scopes=["read:confluence-space:summary", "read:confluence-content.all"],
        capabilities=[
            IntegrationCapability(
                slug="space_search",
                name="Space Search",
                description="Search spaces and page hierarchies.",
                operation="search",
                is_write=False,
                required_scopes=["read:confluence-space:summary"],
            ),
            IntegrationCapability(
                slug="page_retrieval",
                name="Page Retrieval",
                description="Fetch formatted Confluence pages and attachments.",
                operation="read",
                is_write=False,
                required_scopes=["read:confluence-content.all"],
            ),
        ],
    ),
    "google_drive": IntegrationDefinition(
        id="int_google_drive",
        slug="google_drive",
        name="Google Drive",
        description="Search and index Google Docs, Sheets, and Drive files.",
        category="productivity",
        icon="google_drive",
        status="beta",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2"],
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
        capabilities=[
            IntegrationCapability(
                slug="file_search",
                name="File Search",
                description="Search Google Drive by file name, type, and text content.",
                operation="search",
                is_write=False,
                required_scopes=["drive.readonly"],
            ),
            IntegrationCapability(
                slug="file_download",
                name="File Download",
                description="Export and download Docs, PDFs, and Sheets.",
                operation="read",
                is_write=False,
                required_scopes=["drive.readonly"],
            ),
            IntegrationCapability(
                slug="folder_listing",
                name="Folder Listing",
                description="Browse folder trees and team drives.",
                operation="read",
                is_write=False,
                required_scopes=["drive.readonly"],
            ),
        ],
    ),

    # -------------------------------------------------------------
    # 4. GOOGLE
    # -------------------------------------------------------------
    "gmail": IntegrationDefinition(
        id="int_gmail",
        slug="gmail",
        name="Gmail",
        description="Search email threads, parse message contents, and prepare email drafts.",
        category="google",
        icon="gmail",
        status="available",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2"],
        scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        capabilities=[
            IntegrationCapability(
                slug="search_threads",
                name="Search Threads",
                description="Query email threads by sender, subject, date, and query.",
                operation="search",
                is_write=False,
                required_scopes=["gmail.readonly"],
            ),
            IntegrationCapability(
                slug="read_messages",
                name="Read Messages",
                description="Parse raw and formatted message bodies and headers.",
                operation="read",
                is_write=False,
                required_scopes=["gmail.readonly"],
            ),
            IntegrationCapability(
                slug="send_emails",
                name="Send Emails",
                description="Send outbound notifications and email replies.",
                operation="write",
                is_write=True,
                required_scopes=["gmail.send"],
            ),
        ],
    ),
    "google_calendar": IntegrationDefinition(
        id="int_google_calendar",
        slug="google_calendar",
        name="Google Calendar",
        description="List scheduled meetings, check availability, and schedule events.",
        category="google",
        icon="google_calendar",
        status="beta",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2"],
        scopes=[
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/calendar.events",
        ],
        capabilities=[
            IntegrationCapability(
                slug="list_events",
                name="List Events",
                description="Read calendar events across date ranges.",
                operation="read",
                is_write=False,
                required_scopes=["calendar.readonly"],
            ),
            IntegrationCapability(
                slug="event_details",
                name="Event Details",
                description="Get attendees, locations, and descriptions of calendar events.",
                operation="read",
                is_write=False,
                required_scopes=["calendar.readonly"],
            ),
            IntegrationCapability(
                slug="create_events",
                name="Create Events",
                description="Schedule new calendar appointments.",
                operation="write",
                is_write=True,
                required_scopes=["calendar.events"],
            ),
        ],
    ),
    "google_people": IntegrationDefinition(
        id="int_google_people",
        slug="google_people",
        name="Google People / Contacts",
        description="Search Google Workspace contacts, directory profiles, and emails.",
        category="google",
        icon="google_people",
        status="coming_soon",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2"],
        scopes=["https://www.googleapis.com/auth/contacts.readonly"],
        capabilities=[
            IntegrationCapability(
                slug="search_contacts",
                name="Search Contacts",
                description="Search directory contacts by name, email, or company.",
                operation="search",
                is_write=False,
                required_scopes=["contacts.readonly"],
            ),
            IntegrationCapability(
                slug="contact_details",
                name="Contact Details",
                description="Fetch phone numbers, titles, and addresses.",
                operation="read",
                is_write=False,
                required_scopes=["contacts.readonly"],
            ),
        ],
    ),

    # -------------------------------------------------------------
    # 5. DATABASES
    # -------------------------------------------------------------
    "postgresql": IntegrationDefinition(
        id="int_postgresql",
        slug="postgresql",
        name="PostgreSQL",
        description="Execute read-only SQL queries, inspect table schemas, and retrieve rows.",
        category="databases",
        icon="postgresql",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["connection_string", "database_credentials"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="query",
                name="Query Execution",
                description="Execute safe, parameterized read-only SQL queries.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="schema_inspection",
                name="Schema Inspection",
                description="Discover tables, column types, primary keys, and foreign keys.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="structured_retrieval",
                name="Structured Retrieval",
                description="Retrieve records matching dynamic filter conditions.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "mysql": IntegrationDefinition(
        id="int_mysql",
        slug="mysql",
        name="MySQL",
        description="Connect MySQL databases for schema inspection and query execution.",
        category="databases",
        icon="mysql",
        status="beta",
        connection_modes=["zyntry_managed"],
        auth_methods=["connection_string", "database_credentials"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="query",
                name="Query Execution",
                description="Execute read-only queries against MySQL databases.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="schema_inspection",
                name="Schema Inspection",
                description="Inspect MySQL database tables and columns.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "mongodb": IntegrationDefinition(
        id="int_mongodb",
        slug="mongodb",
        name="MongoDB",
        description="Query MongoDB collections, filter BSON documents, and inspect schemas.",
        category="databases",
        icon="mongodb",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["connection_string", "database_credentials"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="collection_querying",
                name="Collection Querying",
                description="Run aggregation pipelines and find queries on collections.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="document_retrieval",
                name="Document Retrieval",
                description="Fetch documents by ObjectID and attribute filters.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "sqlite": IntegrationDefinition(
        id="int_sqlite",
        slug="sqlite",
        name="SQLite",
        description="Direct local or embedded SQLite database queries and schema discovery.",
        category="databases",
        icon="sqlite",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["file_path", "database_credentials"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="query",
                name="Query Execution",
                description="Execute read-only SQL queries on SQLite database files.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="schema_inspection",
                name="Schema Inspection",
                description="Inspect SQLite tables, views, and indexes.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "cockroachdb": IntegrationDefinition(
        id="int_cockroachdb",
        slug="cockroachdb",
        name="CockroachDB",
        description="Distributed PostgreSQL-compatible SQL query execution and schema inspection.",
        category="databases",
        icon="cockroachdb",
        status="beta",
        connection_modes=["zyntry_managed"],
        auth_methods=["connection_string", "database_credentials"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="query",
                name="Query Execution",
                description="Execute queries against CockroachDB clusters.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="schema_inspection",
                name="Schema Inspection",
                description="Inspect distributed database schemas.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "redis": IntegrationDefinition(
        id="int_redis",
        slug="redis",
        name="Redis",
        description="Fast key-value cache lookups, JSON retrieval, and hash queries.",
        category="databases",
        icon="redis",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["connection_string", "database_credentials"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="key_retrieval",
                name="Key Retrieval",
                description="Get string, JSON, and hash values by key patterns.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="cache_query",
                name="Cache Query",
                description="Query session cache and ephemeral state.",
                operation="read",
                is_write=False,
            ),
        ],
    ),

    # -------------------------------------------------------------
    # 6. STORAGE
    # -------------------------------------------------------------
    "amazon_s3": IntegrationDefinition(
        id="int_amazon_s3",
        slug="amazon_s3",
        name="Amazon S3",
        description="List S3 buckets, download files for RAG indexing, and read object storage.",
        category="storage",
        icon="amazon_s3",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["storage_credentials", "aws_iam_role"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="bucket_listing",
                name="Bucket Listing",
                description="List S3 buckets and object keys matching prefixes.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="object_download",
                name="Object Download",
                description="Download and stream S3 objects for processing.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="object_upload",
                name="Object Upload",
                description="Upload generated reports and exports to S3 buckets.",
                operation="write",
                is_write=True,
            ),
        ],
    ),
    "cloudflare_r2": IntegrationDefinition(
        id="int_cloudflare_r2",
        slug="cloudflare_r2",
        name="Cloudflare R2",
        description="Zero-egress S3-compatible object storage for documents and assets.",
        category="storage",
        icon="cloudflare_r2",
        status="beta",
        connection_modes=["zyntry_managed"],
        auth_methods=["storage_credentials"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="bucket_listing",
                name="Bucket Listing",
                description="List R2 bucket objects.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="object_download",
                name="Object Download",
                description="Download objects from R2 buckets.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="object_upload",
                name="Object Upload",
                description="Upload files to R2 storage.",
                operation="write",
                is_write=True,
            ),
        ],
    ),
    "backblaze_b2": IntegrationDefinition(
        id="int_backblaze_b2",
        slug="backblaze_b2",
        name="Backblaze B2",
        description="Cloud object storage buckets for file retrieval and archival.",
        category="storage",
        icon="backblaze_b2",
        status="coming_soon",
        connection_modes=["zyntry_managed"],
        auth_methods=["storage_credentials"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="bucket_listing",
                name="Bucket Listing",
                description="List B2 bucket contents.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="object_download",
                name="Object Download",
                description="Download files from B2 buckets.",
                operation="read",
                is_write=False,
            ),
        ],
    ),

    # -------------------------------------------------------------
    # 7. WEB / DOCUMENTS
    # -------------------------------------------------------------
    "website": IntegrationDefinition(
        id="int_website",
        slug="website",
        name="Website Crawler",
        description="Crawl public web domains, parse sitemaps, and extract clean text content.",
        category="web_documents",
        icon="website",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["public_url", "bearer_token", "custom_headers"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="web_crawl",
                name="Web Crawl",
                description="Crawl URL trees and extract HTML text.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="html_extraction",
                name="HTML Extraction",
                description="Parse clean readable text and metadata from web pages.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="sitemap_parsing",
                name="Sitemap Parsing",
                description="Discover all pages via sitemap.xml.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "pdf": IntegrationDefinition(
        id="int_pdf",
        slug="pdf",
        name="PDF Documents",
        description="Extract text, tables, and metadata from uploaded PDF documents.",
        category="web_documents",
        icon="pdf",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["file_upload"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="document_parsing",
                name="Document Parsing",
                description="Parse PDF pages and extract text layout.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="text_extraction",
                name="Text Extraction",
                description="Extract raw text and headings.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="vector_indexing",
                name="Vector Indexing",
                description="Chunk and generate embeddings for semantic search.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "docx": IntegrationDefinition(
        id="int_docx",
        slug="docx",
        name="Word Documents (.docx)",
        description="Extract structured text, headings, and tables from Word documents.",
        category="web_documents",
        icon="docx",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["file_upload"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="document_parsing",
                name="Document Parsing",
                description="Parse DOCX paragraphs, lists, and tables.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="text_extraction",
                name="Text Extraction",
                description="Extract clean text for RAG indexing.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "csv": IntegrationDefinition(
        id="int_csv",
        slug="csv",
        name="CSV Spreadsheets",
        description="Parse CSV files, infer column data types, and query tabular records.",
        category="web_documents",
        icon="csv",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["file_upload"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="tabular_parsing",
                name="Tabular Parsing",
                description="Parse rows, headers, and delimiter structures.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="schema_inference",
                name="Schema Inference",
                description="Automatically detect column data types and summaries.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="row_querying",
                name="Row Querying",
                description="Filter and search table rows.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "txt": IntegrationDefinition(
        id="int_txt",
        slug="txt",
        name="Plain Text (.txt)",
        description="Ingest plain text files with automatic sentence and paragraph chunking.",
        category="web_documents",
        icon="txt",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["file_upload"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="text_extraction",
                name="Text Extraction",
                description="Read UTF-8 plain text streams.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="chunking",
                name="Text Chunking",
                description="Split text into semantic chunks for vector storage.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "markdown": IntegrationDefinition(
        id="int_markdown",
        slug="markdown",
        name="Markdown (.md)",
        description="Parse markdown headers, code blocks, and lists into semantic chunks.",
        category="web_documents",
        icon="markdown",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["file_upload"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="markdown_parsing",
                name="Markdown Parsing",
                description="Parse CommonMark and GFM headers, tables, and code blocks.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="section_chunking",
                name="Section Chunking",
                description="Split by H1/H2/H3 boundaries for high-precision retrieval.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "json": IntegrationDefinition(
        id="int_json",
        slug="json",
        name="JSON Data (.json)",
        description="Ingest structured JSON payloads and query nested object hierarchies.",
        category="web_documents",
        icon="json",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["file_upload"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="json_parsing",
                name="JSON Parsing",
                description="Parse valid JSON documents and arrays.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="schema_inference",
                name="Schema Inference",
                description="Extract object keys and nested schema definitions.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "document_storage": IntegrationDefinition(
        id="int_document_storage",
        slug="document_storage",
        name="Uploaded Documents",
        description="Upload and index files (PDF, DOCX, TXT, CSV, Markdown) for RAG vector search.",
        category="web_documents",
        icon="document_storage",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["file_upload"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="document_indexing",
                name="Document Indexing",
                description="Index uploaded documents with pgvector embeddings.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="document_search",
                name="Document Search",
                description="Perform semantic hybrid search over uploaded knowledge files.",
                operation="search",
                is_write=False,
            ),
            IntegrationCapability(
                slug="document_upload",
                name="Document Upload",
                description="Upload new knowledge base documents directly into runtime storage.",
                operation="write",
                is_write=True,
            ),
        ],
    ),
    "mcp": IntegrationDefinition(
        id="int_mcp",
        slug="mcp",
        name="MCP Server",
        description="Connect Model Context Protocol (MCP) servers to expose external tools.",
        category="web_documents",
        icon="mcp",
        status="available",
        connection_modes=["zyntry_managed"],
        auth_methods=["mcp_config", "stdio", "sse"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="tool_discovery",
                name="Tool Discovery",
                description="Discover tools, prompts, and resources exposed by an MCP server.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="tool_execution",
                name="Tool Execution",
                description="Execute remote MCP tool calls dynamically during runtime execution.",
                operation="execute",
                is_write=True,
            ),
            IntegrationCapability(
                slug="resource_reading",
                name="Resource Reading",
                description="Read dynamic context resources provided by MCP servers.",
                operation="read",
                is_write=False,
            ),
        ],
    ),

    # -------------------------------------------------------------
    # 8. GIS / GEOSPATIAL
    # -------------------------------------------------------------
    "postgis": IntegrationDefinition(
        id="int_postgis",
        slug="postgis",
        name="PostGIS",
        description="Spatial database queries, geometry intersection, and GeoJSON export.",
        category="geospatial",
        icon="postgis",
        status="beta",
        connection_modes=["zyntry_managed"],
        auth_methods=["connection_string", "database_credentials"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="spatial_query",
                name="Spatial Query",
                description="Execute spatial boundary and proximity queries.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="geometry_inspection",
                name="Geometry Inspection",
                description="Inspect spatial reference systems and coordinate columns.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="geojson_export",
                name="GeoJSON Export",
                description="Convert query results to GeoJSON feature collections.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "arcgis": IntegrationDefinition(
        id="int_arcgis",
        slug="arcgis",
        name="ArcGIS",
        description="Connect Esri ArcGIS REST Feature Services and geospatial layers.",
        category="geospatial",
        icon="arcgis",
        status="coming_soon",
        connection_modes=["zyntry_managed", "end_user_oauth"],
        auth_methods=["oauth2", "api_key"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="feature_service_query",
                name="Feature Service Query",
                description="Query spatial feature layers and attributes.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="layer_metadata",
                name="Layer Metadata",
                description="Read service capabilities, extents, and fields.",
                operation="read",
                is_write=False,
            ),
        ],
    ),
    "geoserver": IntegrationDefinition(
        id="int_geoserver",
        slug="geoserver",
        name="GeoServer",
        description="Query OGC WFS (Web Feature Service) and inspect map layer catalogs.",
        category="geospatial",
        icon="geoserver",
        status="coming_soon",
        connection_modes=["zyntry_managed"],
        auth_methods=["basic_auth", "api_key"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="wfs_query",
                name="WFS Query",
                description="Query vector features via WFS getFeature requests.",
                operation="read",
                is_write=False,
            ),
            IntegrationCapability(
                slug="wms_metadata",
                name="WMS Metadata",
                description="Inspect layer bounds and map styles.",
                operation="read",
                is_write=False,
            ),
        ],
    ),

    # -------------------------------------------------------------
    # 9. AI PROVIDERS
    # -------------------------------------------------------------
    "openai": IntegrationDefinition(
        id="int_openai",
        slug="openai",
        name="OpenAI",
        description="GPT-4o, GPT-4o-mini, o1, o3-mini models and text-embedding-3 vectors.",
        category="ai_providers",
        icon="openai",
        status="available",
        connection_modes=["zyntry_managed", "api_key"],
        auth_methods=["api_key"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="chat_completion",
                name="Chat Completion",
                description="High-speed text and reasoning model generation.",
                operation="execute",
                is_write=False,
            ),
            IntegrationCapability(
                slug="embeddings",
                name="Embeddings",
                description="Generate vector embeddings for semantic search.",
                operation="execute",
                is_write=False,
            ),
            IntegrationCapability(
                slug="tool_calling",
                name="Tool Calling",
                description="Structured JSON function and tool calling.",
                operation="execute",
                is_write=False,
            ),
        ],
    ),
    "anthropic": IntegrationDefinition(
        id="int_anthropic",
        slug="anthropic",
        name="Anthropic",
        description="Claude 3.5 Sonnet, Claude 3.5 Haiku, and Claude 3 Opus models.",
        category="ai_providers",
        icon="anthropic",
        status="available",
        connection_modes=["zyntry_managed", "api_key"],
        auth_methods=["api_key"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="chat_completion",
                name="Chat Completion",
                description="High-reasoning Claude chat completions.",
                operation="execute",
                is_write=False,
            ),
            IntegrationCapability(
                slug="tool_calling",
                name="Tool Calling",
                description="Claude native tool and function invocation.",
                operation="execute",
                is_write=False,
            ),
        ],
    ),
    "google_gemini": IntegrationDefinition(
        id="int_google_gemini",
        slug="google_gemini",
        name="Google Gemini",
        description="Gemini 2.0 Flash, Gemini 1.5 Pro, and multimodal reasoning models.",
        category="ai_providers",
        icon="google_gemini",
        status="available",
        connection_modes=["zyntry_managed", "api_key"],
        auth_methods=["api_key"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="chat_completion",
                name="Chat Completion",
                description="Fast multimodal and long-context text completions.",
                operation="execute",
                is_write=False,
            ),
            IntegrationCapability(
                slug="multimodal_inference",
                name="Multimodal Inference",
                description="Process image, audio, and video inputs.",
                operation="execute",
                is_write=False,
            ),
            IntegrationCapability(
                slug="embeddings",
                name="Embeddings",
                description="Generate text-embedding-004 vectors.",
                operation="execute",
                is_write=False,
            ),
        ],
    ),
    "deepseek": IntegrationDefinition(
        id="int_deepseek",
        slug="deepseek",
        name="DeepSeek",
        description="DeepSeek-V3 and DeepSeek-R1 reasoning models.",
        category="ai_providers",
        icon="deepseek",
        status="available",
        connection_modes=["zyntry_managed", "api_key"],
        auth_methods=["api_key"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="chat_completion",
                name="Chat Completion",
                description="Cost-effective reasoning and code completions.",
                operation="execute",
                is_write=False,
            ),
            IntegrationCapability(
                slug="code_generation",
                name="Code Generation",
                description="Specialized code completion and refactoring.",
                operation="execute",
                is_write=False,
            ),
        ],
    ),
    "mistral": IntegrationDefinition(
        id="int_mistral",
        slug="mistral",
        name="Mistral AI",
        description="Mistral Large, Mistral Small, and Codestral model inference.",
        category="ai_providers",
        icon="mistral",
        status="beta",
        connection_modes=["zyntry_managed", "api_key"],
        auth_methods=["api_key"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="chat_completion",
                name="Chat Completion",
                description="Mistral language model completions.",
                operation="execute",
                is_write=False,
            ),
            IntegrationCapability(
                slug="embeddings",
                name="Embeddings",
                description="Mistral embedding vectors.",
                operation="execute",
                is_write=False,
            ),
        ],
    ),
    "xai": IntegrationDefinition(
        id="int_xai",
        slug="xai",
        name="xAI (Grok)",
        description="Grok-2 and Grok-2-vision real-time inference models.",
        category="ai_providers",
        icon="xai",
        status="beta",
        connection_modes=["zyntry_managed", "api_key"],
        auth_methods=["api_key"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="chat_completion",
                name="Chat Completion",
                description="Grok chat completions with high speed.",
                operation="execute",
                is_write=False,
            ),
        ],
    ),
    "groq": IntegrationDefinition(
        id="int_groq",
        slug="groq",
        name="Groq LPU",
        description="Ultra-low latency LPU hardware inference for open-source models.",
        category="ai_providers",
        icon="groq",
        status="beta",
        connection_modes=["zyntry_managed", "api_key"],
        auth_methods=["api_key"],
        scopes=[],
        capabilities=[
            IntegrationCapability(
                slug="fast_inference",
                name="Fast Inference",
                description="Sub-100ms Llama 3 and Mixtral model completions.",
                operation="execute",
                is_write=False,
            ),
        ],
    ),
}

# Add canonical aliases so both "postgres" and "postgresql", "s3" and "amazon_s3" work seamlessly
ALIASES: dict[str, str] = {
    "postgres": "postgresql",
    "s3": "amazon_s3",
    "gdrive": "google_drive",
    "docs": "document_storage",
    "documentation": "document_storage",
    "gemini": "google_gemini",
    "grok": "xai",
}


class IntegrationRegistry:
    def __init__(self) -> None:
        self._definitions = DEFINITIONS
        self._aliases = ALIASES

    def get(self, slug_or_id: str) -> IntegrationDefinition | None:
        key = slug_or_id.lower().strip()
        if key in self._aliases:
            key = self._aliases[key]
        if key in self._definitions:
            return self._definitions[key]
        for defn in self._definitions.values():
            if defn.id == key or defn.slug == key:
                return defn
        return None

    def list_all(
        self,
        category: str | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> list[IntegrationDefinition]:
        items = list(self._definitions.values())
        if category:
            cat = category.lower().strip()
            items = [i for i in items if i.category.lower() == cat]
        if status:
            st = status.lower().strip()
            items = [i for i in items if i.status.lower() == st]
        if search:
            q = search.lower().strip()
            items = [
                i for i in items
                if q in i.name.lower() or q in i.slug.lower() or q in i.description.lower()
            ]
        return items

    def list_slugs(self, status: str | None = None) -> list[str]:
        if status:
            return [defn.slug for defn in self._definitions.values() if defn.status == status]
        return list(self._definitions.keys())

    def is_available(self, slug_or_id: str) -> bool:
        defn = self.get(slug_or_id)
        if defn is None:
            return False
        return defn.status in ("available", "beta")


integration_registry = IntegrationRegistry()

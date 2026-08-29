from __future__ import annotations

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Any

logger = logging.getLogger(__name__)

_POSTGRES_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$")


def _safe_postgres_identifier(value: object) -> str | None:
    """Return a quoted table identifier or reject user-controlled SQL text."""
    if not isinstance(value, str) or not _POSTGRES_IDENTIFIER_RE.fullmatch(value):
        return None
    return ".".join(f'"{part}"' for part in value.split("."))


async def _emit_change(project_id: str, organization_id: str | None, source_id: str, event_type: str, data: dict) -> None:
    try:
        from app.utils.events import emit_project_event
        await emit_project_event(project_id, organization_id, event_type, {"source_id": source_id, **data})
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Failed to emit watcher event %s: %s", event_type, exc)


class BaseWatcher(ABC):
    def __init__(self, connector: Any, poll_interval: int = 60) -> None:
        self.connector = connector
        self.poll_interval = poll_interval
        self._running = False
        self._task: asyncio.Task | None = None
        self.last_sync_timestamp: str | None = None
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 5
        self._reconnect_backoff = 1.0

    @abstractmethod
    async def poll(self) -> None:
        raise NotImplementedError

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._reconnect_attempts = 0
        self._reconnect_backoff = 1.0
        self._task = asyncio.ensure_future(self._run_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await self.poll()
                self._reconnect_attempts = 0
                self._reconnect_backoff = 1.0
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Watcher poll error for %s: %s", self.__class__.__name__, exc)
                self._reconnect_attempts += 1
                if self._reconnect_attempts >= self._max_reconnect_attempts:
                    logger.error("Max reconnect attempts reached for watcher %s", self.__class__.__name__)
                    await self._emit_error("max_reconnect_attempts_reached", str(exc))
                    break
                await asyncio.sleep(self._reconnect_backoff)
                self._reconnect_backoff = min(self._reconnect_backoff * 2, 60.0)
                continue
            await asyncio.sleep(self.poll_interval)

    async def _emit_error(self, event_type: str, message: str) -> None:
        project_id = getattr(self.connector, "project_id", "")
        organization_id = getattr(self.connector, "organization_id", None)
        source_id = getattr(self.connector, "source_id", "")
        await _emit_change(project_id, organization_id, source_id, event_type, {"error": message})

    async def watch(self, callback: Any) -> None:
        self.callback = callback
        await self.start()

    def _since(self) -> str | None:
        return self.last_sync_timestamp


class GitHubWatcher(BaseWatcher):
    def __init__(self, connector: Any, poll_interval: int = 120) -> None:
        super().__init__(connector, poll_interval)

    async def poll(self) -> None:
        token = self.connector.credentials.get("access_token") or self.connector.credentials.get("token")
        repo = self.connector.config.get("repo")
        if not token or not repo:
            logger.warning("GitHubWatcher: missing token or repo config")
            return

        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        since = self._since()

        if since:
            headers["If-Modified-Since"] = since

        async def _request(url: str) -> Any:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    if response.status == 304:
                        return None
                    if response.status == 403:
                        text = await response.text()
                        raise RuntimeError(f"GitHub rate limit or forbidden: {text}")
                    response.raise_for_status()
                    return await response.json()

        commits_url = f"https://api.github.com/repos/{repo}/commits"
        commits = await _request(commits_url)
        if commits is None:
            return

        for commit in commits:
            sha = commit.get("sha", "")
            message = commit.get("commit", {}).get("message", "")
            author = commit.get("commit", {}).get("author", {})
            timestamp = commit.get("commit", {}).get("author", {}).get("date", "")
            if timestamp:
                self.last_sync_timestamp = timestamp
            event_data = {
                "event_type": "commit",
                "sha": sha,
                "message": message,
                "author": author.get("name"),
                "timestamp": timestamp,
            }
            if self.callback:
                await self.callback(event_data)

        if commits:
            await _emit_change(
                self.connector.project_id,
                getattr(self.connector, "organization_id", None),
                self.connector.source_id,
                "source.git.commit",
                {"count": len(commits), "commits": commits},
            )

        branches_url = f"https://api.github.com/repos/{repo}/branches"
        branches = await _request(branches_url)
        if branches:
            for branch in branches:
                name = branch.get("name", "")
                sha = branch.get("commit", {}).get("sha", "")
                await _emit_change(
                    self.connector.project_id,
                    getattr(self.connector, "organization_id", None),
                    self.connector.source_id,
                    "source.git.branch",
                    {"branch": name, "sha": sha},
                )

        events_url = f"https://api.github.com/repos/{repo}/events"
        events = await _request(events_url)
        if events:
            for event in events:
                event_type = event.get("type", "")
                if event_type == "PushEvent":
                    await _emit_change(
                        self.connector.project_id,
                        getattr(self.connector, "organization_id", None),
                        self.connector.source_id,
                        "source.git.push",
                        {"event": event_type, "ref": event.get("ref", "")},
                    )
                elif event_type == "DeleteEvent":
                    await _emit_change(
                        self.connector.project_id,
                        getattr(self.connector, "organization_id", None),
                        self.connector.source_id,
                        "source.git.delete",
                        {"ref": event.get("ref", ""), "ref_type": event.get("payload", {}).get("ref_type", "")},
                    )
                elif event_type == "RenameFileEvent":
                    await _emit_change(
                        self.connector.project_id,
                        getattr(self.connector, "organization_id", None),
                        self.connector.source_id,
                        "source.git.rename",
                        {
                            "old_name": event.get("payload", {}).get("rename", [{}])[0].get("from"),
                            "new_name": event.get("payload", {}).get("rename", [{}])[0].get("to"),
                        },
                    )
                elif event_type == "PullRequestEvent":
                    action = event.get("payload", {}).get("action", "")
                    if action == "closed" and event.get("payload", {}).get("pull_request", {}).get("merged"):
                        await _emit_change(
                            self.connector.project_id,
                            getattr(self.connector, "organization_id", None),
                            self.connector.source_id,
                            "source.git.pr.merged",
                            {
                                "pr_number": event.get("payload", {}).get("pull_request", {}).get("number"),
                                "title": event.get("payload", {}).get("pull_request", {}).get("title"),
                            },
                        )


class GoogleDriveWatcher(BaseWatcher):
    def __init__(self, connector: Any, poll_interval: int = 180) -> None:
        super().__init__(connector, poll_interval)

    async def poll(self) -> None:
        token = self.connector.credentials.get("access_token") or self.connector.credentials.get("token")
        if not token:
            logger.warning("GoogleDriveWatcher: missing token")
            return

        headers = {"Authorization": f"Bearer {token}"}
        since = self._since()
        query = "trashed = false"
        if since:
            query += f" and modifiedTime > '{since}'"

        async def _request(url: str) -> Any:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    return await response.json()

        files_url = f"https://www.googleapis.com/drive/v3/files?q={query}&fields=files(id,name,mimeType,modifiedTime,trashed,size)"
        data = await _request(files_url)
        files = data.get("files", [])

        for file in files:
            modified = file.get("modifiedTime", "")
            if modified:
                self.last_sync_timestamp = modified
            trashed = file.get("trashed", False)
            if trashed:
                await _emit_change(
                    self.connector.project_id,
                    getattr(self.connector, "organization_id", None),
                    self.connector.source_id,
                    "source.gdrive.deleted",
                    {"file_id": file.get("id"), "name": file.get("name")},
                )
            else:
                await _emit_change(
                    self.connector.project_id,
                    getattr(self.connector, "organization_id", None),
                    self.connector.source_id,
                    "source.gdrive.updated",
                    {"file_id": file.get("id"), "name": file.get("name"), "mime_type": file.get("mimeType"), "modified_time": modified},
                )

        changes_url = f"https://www.googleapis.com/drive/v3/changes?pageToken={self.connector.config.get('start_page_token', '')}&fields=changes(fileId,removed,file(name,mimeType,modifiedTime))"
        if since:
            changes_url += f"&startTime={since}"
        changes_data = await _request(changes_url)
        changes = changes_data.get("changes", [])
        for change in changes:
            file_id = change.get("fileId", "")
            removed = change.get("removed", False)
            file_info = change.get("file", {})
            if removed:
                await _emit_change(
                    self.connector.project_id,
                    getattr(self.connector, "organization_id", None),
                    self.connector.source_id,
                    "source.gdrive.deleted",
                    {"file_id": file_id, "name": file_info.get("name")},
                )
            else:
                await _emit_change(
                    self.connector.project_id,
                    getattr(self.connector, "organization_id", None),
                    self.connector.source_id,
                    "source.gdrive.updated",
                    {"file_id": file_id, "name": file_info.get("name"), "mime_type": file_info.get("mimeType"), "modified_time": file_info.get("modifiedTime")},
                )


class NotionWatcher(BaseWatcher):
    def __init__(self, connector: Any, poll_interval: int = 150) -> None:
        super().__init__(connector, poll_interval)

    async def poll(self) -> None:
        token = self.connector.credentials.get("access_token") or self.connector.credentials.get("token")
        if not token:
            logger.warning("NotionWatcher: missing token")
            return

        headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

        async def _request(url: str, method: str = "GET", body: dict | None = None) -> Any:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=headers, json=body) as response:
                    response.raise_for_status()
                    return await response.json()

        databases = self.connector.config.get("databases", [])
        since = self._since()
        for db_id in databases:
            query_body: dict = {}
            if since:
                query_body["filter"] = {"timestamp": "last_edited_time", "created_time_start": since}
            query_body["page_size"] = 100
            url = f"https://api.notion.com/v1/databases/{db_id}/query"
            data = await _request(url, "POST", query_body)
            for page in data.get("results", []):
                page_id = page.get("id", "")
                title_parts = page.get("properties", {}).get("title", {}).get("title", [])
                title = title_parts[0].get("plain_text", "") if title_parts else ""
                last_edited = page.get("last_edited_time", "")
                if last_edited:
                    self.last_sync_timestamp = last_edited
                await _emit_change(
                    self.connector.project_id,
                    getattr(self.connector, "organization_id", None),
                    self.connector.source_id,
                    "source.notion.page.updated",
                    {"page_id": page_id, "title": title, "last_edited_time": last_edited},
                )

        children_url = f"https://api.notion.com/v1/blocks/{self.connector.config.get('root_page_id', '')}/children"
        children = await _request(children_url)
        for child in children.get("results", []):
            child_id = child.get("id", "")
            child_type = child.get("type", "")
            edited_time = child.get("last_edited_time", "")
            if edited_time:
                self.last_sync_timestamp = edited_time
            await _emit_change(
                self.connector.project_id,
                getattr(self.connector, "organization_id", None),
                self.connector.source_id,
                "source.notion.block.updated",
                {"block_id": child_id, "block_type": child_type, "last_edited_time": edited_time},
            )


class SlackWatcher(BaseWatcher):
    def __init__(self, connector: Any, poll_interval: int = 60) -> None:
        super().__init__(connector, poll_interval)

    async def poll(self) -> None:
        token = self.connector.credentials.get("bot_token") or self.connector.credentials.get("access_token")
        if not token:
            logger.warning("SlackWatcher: missing token")
            return

        headers = {"Authorization": f"Bearer {token}"}
        channel_id = self.connector.config.get("channel_id")
        since = self._since()
        oldest = str(int(time.time()) - 86400)
        if since:
            oldest = since

        async def _request(url: str) -> Any:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    return await response.json()

        if channel_id:
            history_url = f"https://slack.com/api/conversations.history?channel={channel_id}&oldest={oldest}&limit=100"
            data = await _request(history_url)
            if data.get("ok"):
                for message in data.get("messages", []):
                    ts = message.get("ts", "")
                    if ts:
                        self.last_sync_timestamp = ts
                    await _emit_change(
                        self.connector.project_id,
                        getattr(self.connector, "organization_id", None),
                        self.connector.source_id,
                        "source.slack.message",
                        {
                            "channel": channel_id,
                            "ts": ts,
                            "user": message.get("user"),
                            "text": message.get("text", ""),
                            "type": message.get("type"),
                        },
                    )

        reactions_url = "https://slack.com/api/reactions.list?limit=100"
        reactions_data = await _request(reactions_url)
        if reactions_data.get("ok"):
            for item in reactions_data.get("items", []):
                reaction = item.get("reaction", "")
                channel = item.get("channel", "")
                ts = item.get("message", {}).get("ts", "")
                await _emit_change(
                    self.connector.project_id,
                    getattr(self.connector, "organization_id", None),
                    self.connector.source_id,
                    "source.slack.reaction",
                    {"reaction": reaction, "channel": channel, "ts": ts},
                )


class PostgresWatcher(BaseWatcher):
    def __init__(self, connector: Any, poll_interval: int = 90) -> None:
        super().__init__(connector, poll_interval)

    async def poll(self) -> None:
        import asyncpg

        dsn = self.connector.config.get("dsn")
        if not dsn:
            logger.warning("PostgresWatcher: missing dsn")
            return

        host = self.connector.config.get("host")
        port = self.connector.config.get("port", 5432)
        user = self.connector.config.get("user")
        password = self.connector.config.get("password")
        database = self.connector.config.get("database")

        conn = None
        try:
            if dsn:
                conn = await asyncpg.connect(dsn=dsn)
            else:
                conn = await asyncpg.connect(host=host, port=port, user=user, password=password, database=database)

            tables = self.connector.config.get("tables", [])
            since = self._since()
            for configured_table in tables:
                table = _safe_postgres_identifier(configured_table)
                if table is None:
                    logger.warning("PostgresWatcher: ignoring invalid table identifier")
                    continue
                if since:
                    query = f"SELECT * FROM {table} WHERE updated_at > $1"  # nosec B608 - table is validated and quoted above
                    rows = await conn.fetch(query, since)
                else:
                    query = f"SELECT * FROM {table} LIMIT 100"  # nosec B608 - table is validated and quoted above
                    rows = await conn.fetch(query)

                for row in rows:
                    row_dict = dict(row)
                    updated_at = str(row_dict.get("updated_at", ""))
                    if updated_at:
                        self.last_sync_timestamp = updated_at
                    await _emit_change(
                        self.connector.project_id,
                        getattr(self.connector, "organization_id", None),
                        self.connector.source_id,
                        "source.postgres.row.updated",
                        {"table": configured_table, "row": row_dict},
                    )

        except Exception as exc:
            logger.error("PostgresWatcher poll error: %s", exc)
            raise
        finally:
            if conn:
                await conn.close()


class WatcherManager:
    def __init__(self) -> None:
        self._watchers: dict[str, BaseWatcher] = {}
        self._lock = asyncio.Lock()

    def register(self, source_id: str, watcher: BaseWatcher) -> None:
        self._watchers[source_id] = watcher

    async def start_source(self, source_id: str, connector: Any, poll_interval: int = 60) -> None:
        async with self._lock:
            watcher = self._watchers.get(source_id)
            if watcher is None:
                source_type = connector.config.get("source_type", "").lower()
                watcher_map = {
                    "github": GitHubWatcher,
                    "google_drive": GoogleDriveWatcher,
                    "notion": NotionWatcher,
                    "slack": SlackWatcher,
                    "postgres": PostgresWatcher,
                }
                watcher_class = watcher_map.get(source_type)
                if not watcher_class:
                    raise ValueError(f"No watcher for source type: {source_type}")
                watcher = watcher_class(connector, poll_interval=poll_interval)
                self._watchers[source_id] = watcher
        await watcher.start()

    async def stop_source(self, source_id: str) -> None:
        watcher = self._watchers.get(source_id)
        if watcher:
            await watcher.stop()

    async def stop_all(self) -> None:
        for source_id in list(self._watchers.keys()):
            await self.stop_source(source_id)

    def get_active(self) -> list[str]:
        return [sid for sid, watcher in self._watchers.items() if watcher._running]

    async def restart_source(self, source_id: str, connector: Any, poll_interval: int = 60) -> None:
        await self.stop_source(source_id)
        await self.start_source(source_id, connector, poll_interval)


watcher_manager = WatcherManager()

"""Action providers for the Google Workspace and Cloud integrations.

Every mutating operation is marked with a write permission and medium/high
risk.  The actions router turns that metadata into a confirmation request;
the provider also fails closed when it is called from an unconfirmed workflow.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import quote

import httpx

from app.schemas.actions import ActionDefinition, ActionResponse
from app.services.actions.base import BaseActionProvider
from app.services.actions.registry import ActionRegistry


class GoogleServiceActionProvider(BaseActionProvider):
    provider_name = "google_service"
    base_url = "https://www.googleapis.com"
    # action -> (method, path template, required arguments, query arguments, body mode)
    routes: dict[str, tuple[str, str, tuple[str, ...], tuple[str, ...], str | None]] = {}
    action_specs: tuple[dict[str, Any], ...] = ()

    def __init__(self, credentials: dict[str, Any] | None = None) -> None:
        self._token = (credentials or {}).get("access_token") or (credentials or {}).get("token")

    def list_actions(self) -> list[ActionDefinition]:
        return [ActionDefinition(provider=self.provider_name, **spec) for spec in self.action_specs]

    async def validate(self, action: str, arguments: dict[str, Any]) -> bool:
        route = self.routes.get(action)
        if route is None:
            return False
        return all(key in arguments and arguments[key] not in (None, "") for key in route[2])

    async def execute(
        self,
        action: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> ActionResponse:
        if not self._token:
            return ActionResponse(
                success=False,
                error="No Google access token provided. Connect the integration first.",
            )
        route = self.routes.get(action)
        if route is None:
            return ActionResponse(success=False, error=f"Unknown action: {action}")
        if not await self.validate(action, arguments):
            return ActionResponse(success=False, error=f"Invalid arguments for action: {action}")

        definition = next((item for item in self.list_actions() if item.name == action), None)
        is_write = bool(definition and definition.required_permissions)
        if is_write and not context.get("confirmed", False):
            return ActionResponse(
                success=False,
                error="Confirmation required before changing Google data",
                requires_confirmation=True,
                confirmation_reason=f"{action} changes data in {self.provider_name}",
            )

        method, template, _, query_keys, body_mode = route
        path_args = {
            key: quote(str(value), safe="/:,()")
            for key, value in arguments.items()
            if isinstance(value, (str, int))
        }
        try:
            path = template.format(**path_args)
        except KeyError as exc:
            return ActionResponse(success=False, error=f"Missing path argument: {exc.args[0]}")
        params = {key: arguments[key] for key in query_keys if key in arguments}
        body: Any = None
        content: str | bytes | None = None
        if body_mode == "json":
            body = arguments.get("body")
            if body is None:
                path_keys = set(re.findall(r"\{([^}]+)\}", template))
                body = {
                    key: value
                    for key, value in arguments.items()
                    if key not in set(query_keys) and key not in path_keys
                }
        elif body_mode == "values":
            body = {
                "values": arguments.get("values", []),
                "majorDimension": arguments.get("major_dimension", "ROWS"),
            }
        elif body_mode == "text":
            body = {"text": arguments.get("text", "")}
        elif body_mode == "raw":
            content = arguments.get("content", "")

        try:
            headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/json"}
            if body is not None:
                headers["Content-Type"] = "application/json"
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
                response = await client.request(
                    method,
                    f"{self.base_url.rstrip('/')}/{path.lstrip('/')}",
                    headers=headers,
                    params=params,
                    json=body if content is None else None,
                    content=content,
                )
            response.raise_for_status()
            result = response.json() if response.content else {"status": "ok"}
            return ActionResponse(success=True, result=result)
        except httpx.HTTPStatusError as exc:
            return ActionResponse(
                success=False,
                error=f"{self.provider_name} API error {exc.response.status_code}: {exc.response.text}",
            )
        except Exception as exc:
            return ActionResponse(success=False, error=str(exc))


def _read(name: str, description: str) -> dict[str, Any]:
    return {"name": name, "description": description, "risk": "low"}


def _write(name: str, description: str, *, risk: str = "medium") -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "risk": risk,
        "required_permissions": ["write"],
    }


class GooglePeopleActionProvider(GoogleServiceActionProvider):
    provider_name = "google_people"
    routes = {
        "search_contacts": ("GET", "/v1/people:searchContacts", (), ("query", "page_size"), None),
        "contact_details": ("GET", "/v1/{resource_name}", ("resource_name",), (), None),
        "directory_search": ("GET", "/admin/directory/v1/users", (), ("query", "domain", "max_results"), None),
        "directory_user_details": ("GET", "/admin/directory/v1/users/{user_key}", ("user_key",), (), None),
        "search_groups": ("GET", "/admin/directory/v1/groups", (), ("query", "domain", "max_results"), None),
        "group_membership": ("GET", "/admin/directory/v1/groups/{group_key}/members", ("group_key",), ("max_results",), None),
    }
    action_specs = (
        _read("search_contacts", "Search Google contacts"),
        _read("contact_details", "Get contact details"),
        _read("directory_search", "Search the Workspace directory"),
        _read("directory_user_details", "Get a Workspace user profile"),
        _read("search_groups", "Search Workspace groups"),
        _read("group_membership", "List group members"),
    )


class GoogleSheetsActionProvider(GoogleServiceActionProvider):
    provider_name = "google_sheets"
    base_url = "https://sheets.googleapis.com"
    routes = {
        "search_spreadsheets": ("GET", "/drive/v3/files", (), ("q", "page_size"), None),
        "spreadsheet_metadata": ("GET", "/v4/spreadsheets/{spreadsheet_id}", ("spreadsheet_id",), (), None),
        "read_ranges": ("GET", "/v4/spreadsheets/{spreadsheet_id}/values/{range}", ("spreadsheet_id", "range"), (), None),
        "query_rows": ("GET", "/v4/spreadsheets/{spreadsheet_id}/values/{range}", ("spreadsheet_id", "range"), (), None),
        "append_rows": ("POST", "/v4/spreadsheets/{spreadsheet_id}/values/{range}:append", ("spreadsheet_id", "range", "values"), ("value_input_option",), "values"),
        "update_cells": ("PUT", "/v4/spreadsheets/{spreadsheet_id}/values/{range}", ("spreadsheet_id", "range", "values"), ("value_input_option",), "values"),
        "create_spreadsheet": ("POST", "/v4/spreadsheets", (), (), "json"),
    }
    action_specs = (
        _read("search_spreadsheets", "Search spreadsheets through Drive metadata"),
        _read("spreadsheet_metadata", "Read spreadsheet metadata"),
        _read("read_ranges", "Read worksheet cells"),
        _read("query_rows", "Query worksheet rows"),
        _write("append_rows", "Append rows to a worksheet"),
        _write("update_cells", "Update worksheet cells"),
        _write("create_spreadsheet", "Create a spreadsheet"),
    )

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        if action == "search_spreadsheets":
            original_base_url = self.base_url
            self.base_url = "https://www.googleapis.com"
            try:
                return await super().execute(action, arguments, context)
            finally:
                self.base_url = original_base_url
        return await super().execute(action, arguments, context)


class GoogleDocsActionProvider(GoogleServiceActionProvider):
    provider_name = "google_docs"
    base_url = "https://docs.googleapis.com"
    routes = {
        "search_documents": ("GET", "/drive/v3/files", (), ("q", "page_size"), None),
        "read_document": ("GET", "/v1/documents/{document_id}", ("document_id",), (), None),
        "export_document": ("GET", "/v1/documents/{document_id}", ("document_id",), (), None),
        "read_comments": ("GET", "/drive/v3/files/{document_id}/comments", ("document_id",), (), None),
        "create_document": ("POST", "/v1/documents", (), (), "json"),
        "update_document": ("POST", "/v1/documents/{document_id}:batchUpdate", ("document_id", "body"), (), "json"),
        "append_content": ("POST", "/v1/documents/{document_id}:batchUpdate", ("document_id", "body"), (), "json"),
    }
    action_specs = (
        _read("search_documents", "Search documents through Drive metadata"),
        _read("read_document", "Read document structure and text"),
        _read("export_document", "Export a document"),
        _read("read_comments", "Read document comments"),
        _write("create_document", "Create a document"),
        _write("update_document", "Update document content"),
        _write("append_content", "Append content to a document"),
    )

    async def execute(self, action: str, arguments: dict[str, Any], context: dict[str, Any]) -> ActionResponse:
        if action == "search_documents":
            original_base_url = self.base_url
            self.base_url = "https://www.googleapis.com"
            try:
                return await super().execute(action, arguments, context)
            finally:
                self.base_url = original_base_url
        return await super().execute(action, arguments, context)


class GoogleChatActionProvider(GoogleServiceActionProvider):
    provider_name = "google_chat"
    base_url = "https://chat.googleapis.com"
    routes = {
        "list_spaces": ("GET", "/v1/spaces", (), ("page_size",), None),
        "search_messages": ("GET", "/v1/{space}/messages", ("space",), ("filter", "page_size"), None),
        "retrieve_threads": ("GET", "/v1/{space}/messages", ("space",), ("filter", "page_size"), None),
        "list_members": ("GET", "/v1/{space}/members", ("space",), ("page_size",), None),
        "send_messages": ("POST", "/v1/{space}/messages", ("space", "text"), (), "text"),
    }
    action_specs = (
        _read("list_spaces", "List Chat spaces"),
        _read("search_messages", "Search Chat messages"),
        _read("retrieve_threads", "Read a Chat thread"),
        _read("list_members", "List space members"),
        _write("send_messages", "Send a Chat message"),
    )


class GoogleMeetActionProvider(GoogleServiceActionProvider):
    provider_name = "google_meet"
    base_url = "https://meet.googleapis.com"
    routes = {
        "list_meetings": ("GET", "/v2/conferenceRecords", (), ("page_size",), None),
        "meeting_details": ("GET", "/v2/{conference_record_id}", ("conference_record_id",), (), None),
        "participants": ("GET", "/v2/{conference_record_id}/participants", ("conference_record_id",), ("page_size",), None),
        "transcripts": ("GET", "/v2/{conference_record_id}/transcripts", ("conference_record_id",), ("page_size",), None),
        "recordings_metadata": ("GET", "/v2/{conference_record_id}/recordings", ("conference_record_id",), ("page_size",), None),
    }
    action_specs = tuple(_read(name, description) for name, description in (
        ("list_meetings", "List Meet conferences"),
        ("meeting_details", "Read conference details"),
        ("participants", "List meeting participants"),
        ("transcripts", "Retrieve meeting transcripts"),
        ("recordings_metadata", "Read recording metadata"),
    ))


class GoogleFormsActionProvider(GoogleServiceActionProvider):
    provider_name = "google_forms"
    base_url = "https://forms.googleapis.com"
    routes = {
        "form_metadata": ("GET", "/v1/forms/{form_id}", ("form_id",), (), None),
        "list_questions": ("GET", "/v1/forms/{form_id}", ("form_id",), (), None),
        "list_responses": ("GET", "/v1/forms/{form_id}/responses", ("form_id",), ("page_size",), None),
        "response_details": ("GET", "/v1/forms/{form_id}/responses/{response_id}", ("form_id", "response_id"), (), None),
    }
    action_specs = tuple(_read(name, description) for name, description in (
        ("form_metadata", "Read form metadata"),
        ("list_questions", "List form questions"),
        ("list_responses", "List form responses"),
        ("response_details", "Read a form response"),
    ))


class BigQueryActionProvider(GoogleServiceActionProvider):
    provider_name = "bigquery"
    base_url = "https://bigquery.googleapis.com"
    routes = {
        "list_projects": ("GET", "/bigquery/v2/projects", (), ("max_results",), None),
        "list_datasets": ("GET", "/bigquery/v2/projects/{project_id}/datasets", ("project_id",), ("max_results",), None),
        "table_schema": ("GET", "/bigquery/v2/projects/{project_id}/datasets/{dataset_id}/tables/{table_id}", ("project_id", "dataset_id", "table_id"), (), None),
        "query": ("POST", "/bigquery/v2/projects/{project_id}/queries", ("project_id", "query"), (), "json"),
        "job_status": ("GET", "/bigquery/v2/projects/{project_id}/queries/{job_id}", ("project_id", "job_id"), (), None),
    }
    action_specs = tuple(_read(name, description) for name, description in (
        ("list_projects", "List BigQuery projects"),
        ("list_datasets", "List BigQuery datasets"),
        ("table_schema", "Read a BigQuery table schema"),
        ("query", "Run a read-only BigQuery query"),
        ("job_status", "Read BigQuery job status"),
    ))


class GoogleCloudStorageActionProvider(GoogleServiceActionProvider):
    provider_name = "google_cloud_storage"
    base_url = "https://storage.googleapis.com"
    routes = {
        "list_buckets": ("GET", "/storage/v1/b", (), ("project", "max_results"), None),
        "search_objects": ("GET", "/storage/v1/b/{bucket}/o", ("bucket",), ("prefix", "max_results"), None),
        "object_metadata": ("GET", "/storage/v1/b/{bucket}/o/{object_name}", ("bucket", "object_name"), (), None),
        "download_objects": ("GET", "/download/storage/v1/b/{bucket}/o/{object_name}", ("bucket", "object_name"), ("alt",), None),
        "upload_objects": ("POST", "/upload/storage/v1/b/{bucket}/o", ("bucket", "object_name", "content"), ("uploadType", "name"), "raw"),
        "delete_objects": ("DELETE", "/storage/v1/b/{bucket}/o/{object_name}", ("bucket", "object_name"), (), None),
    }
    action_specs = (
        _read("list_buckets", "List Cloud Storage buckets"),
        _read("search_objects", "Search Cloud Storage objects"),
        _read("object_metadata", "Read object metadata"),
        _read("download_objects", "Download a Cloud Storage object"),
        _write("upload_objects", "Upload a Cloud Storage object"),
        _write("delete_objects", "Delete a Cloud Storage object", risk="high"),
    )


class FirestoreActionProvider(GoogleServiceActionProvider):
    provider_name = "firestore"
    base_url = "https://firestore.googleapis.com"
    routes = {
        "list_collections": ("GET", "/v1/projects/{project_id}/databases/{database_id}/documents", ("project_id", "database_id"), (), None),
        "document_retrieval": ("GET", "/v1/projects/{project_id}/databases/{database_id}/documents/{document_path}", ("project_id", "database_id", "document_path"), (), None),
        "query_documents": ("POST", "/v1/projects/{project_id}/databases/{database_id}/documents:runQuery", ("project_id", "database_id", "body"), (), "json"),
        "write_documents": ("PATCH", "/v1/projects/{project_id}/databases/{database_id}/documents/{document_path}", ("project_id", "database_id", "document_path", "body"), (), "json"),
        "delete_documents": ("DELETE", "/v1/projects/{project_id}/databases/{database_id}/documents/{document_path}", ("project_id", "database_id", "document_path"), (), None),
    }
    action_specs = (
        _read("list_collections", "List Firestore collections"),
        _read("query_documents", "Query Firestore documents"),
        _read("document_retrieval", "Retrieve a Firestore document"),
        _write("write_documents", "Create or update a Firestore document"),
        _write("delete_documents", "Delete a Firestore document", risk="high"),
    )


class GoogleAnalyticsActionProvider(GoogleServiceActionProvider):
    provider_name = "google_analytics"
    base_url = "https://analyticsdata.googleapis.com"
    routes = {
        "list_properties": ("GET", "/v1beta/accountSummaries", (), ("page_size",), None),
        "run_reports": ("POST", "/v1beta/properties/{property_id}:runReport", ("property_id", "body"), (), "json"),
        "query_events": ("POST", "/v1beta/properties/{property_id}:runReport", ("property_id", "body"), (), "json"),
        "query_conversions": ("POST", "/v1beta/properties/{property_id}:runReport", ("property_id", "body"), (), "json"),
    }
    action_specs = tuple(_read(name, description) for name, description in (
        ("list_properties", "List Analytics properties"),
        ("run_reports", "Run a read-only Analytics report"),
        ("query_events", "Query Analytics events"),
        ("query_conversions", "Query Analytics conversions"),
    ))


class GoogleLoggingActionProvider(GoogleServiceActionProvider):
    provider_name = "google_logging"
    base_url = "https://logging.googleapis.com"
    routes = {
        "search_logs": ("POST", "/v2/entries:list", ("project_id",), (), "json"),
        "log_details": ("GET", "/v2/{log_name}", ("log_name",), (), None),
        "aggregate_logs": ("POST", "/v2/entries:list", ("project_id",), (), "json"),
    }
    action_specs = tuple(_read(name, description) for name, description in (
        ("search_logs", "Search Cloud Logging entries"),
        ("log_details", "Read a log entry"),
        ("aggregate_logs", "Aggregate log entries"),
    ))

    async def execute(
        self,
        action: str,
        arguments: dict[str, Any],
        context: dict[str, Any],
    ) -> ActionResponse:
        if action in {"search_logs", "aggregate_logs"} and "body" not in arguments:
            arguments = dict(arguments)
            arguments["body"] = {
                "resourceNames": [f"projects/{arguments['project_id']}"],
                "pageSize": arguments.get("page_size", 100),
                "orderBy": "timestamp desc",
                **({"filter": arguments["filter"]} if arguments.get("filter") else {}),
            }
        return await super().execute(action, arguments, context)


class GoogleMonitoringActionProvider(GoogleServiceActionProvider):
    provider_name = "google_monitoring"
    base_url = "https://monitoring.googleapis.com"
    routes = {
        "query_metrics": ("GET", "/v3/projects/{project_id}/timeSeries", ("project_id",), ("filter", "interval_start", "interval_end", "page_size"), None),
        "list_alerts": ("GET", "/v3/projects/{project_id}/alertPolicies", ("project_id",), ("page_size",), None),
        "incident_details": ("GET", "/v3/{incident_name}", ("incident_name",), (), None),
        "uptime_checks": ("GET", "/v3/projects/{project_id}/uptimeCheckConfigs", ("project_id",), ("page_size",), None),
    }
    action_specs = tuple(_read(name, description) for name, description in (
        ("query_metrics", "Query Cloud Monitoring metrics"),
        ("list_alerts", "List alert policies"),
        ("incident_details", "Read incident details"),
        ("uptime_checks", "List uptime checks"),
    ))


for _provider in (
    GooglePeopleActionProvider,
    GoogleSheetsActionProvider,
    GoogleDocsActionProvider,
    GoogleChatActionProvider,
    GoogleMeetActionProvider,
    GoogleFormsActionProvider,
    BigQueryActionProvider,
    GoogleCloudStorageActionProvider,
    FirestoreActionProvider,
    GoogleAnalyticsActionProvider,
    GoogleLoggingActionProvider,
    GoogleMonitoringActionProvider,
):
    ActionRegistry.register(_provider)

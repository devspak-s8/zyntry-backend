# Zyntry API Documentation

Base URL: `/api/v1`

All endpoints require authentication unless otherwise noted. Authentication is via session cookie `zyntra_session` or Bearer token in the `Authorization` header.

---

## Authentication (`/auth`)

### `POST /auth/register`
**Responsibility:** Register a new user, create an organization, send verification email, and create a session.

**Request Body:**
```json
{
  "email": "string",
  "password": "string",
  "name": "string (optional)"
}
```

**Response:** `AuthMeResponse`

---

### `POST /auth/login`
**Responsibility:** Authenticate a user, create a session, and set refresh token cookie.

**Request Body:**
```json
{
  "email": "string",
  "password": "string"
}
```

**Response:** `AuthMeResponse`

---

### `POST /auth/logout`
**Responsibility:** Revoke the current session token.

**Request Body:** Empty

**Response:** `dict`

---

### `POST /auth/logout-all`
**Responsibility:** Revoke all active sessions for the current user.

**Request Body:** Empty

**Response:** HTTP 204 No Content

---

### `POST /auth/refresh`
**Responsibility:** Refresh the session token using the refresh token cookie.

**Request Body:** Empty

**Response:** `AuthMeResponse`

---

### `GET /auth/me`
**Responsibility:** Get the current authenticated user's information.

**Request Body:** Empty

**Response:** `AuthMeResponse`

---

### `POST /auth/forgot-password`
**Responsibility:** Generate a password reset token and send a reset email.

**Request Body:**
```json
{
  "email": "string"
}
```

**Response:**
```json
{
  "message": "If an account exists with that email, a reset link has been sent."
}
```

---

### `POST /auth/reset-password`
**Responsibility:** Reset the user's password using a valid reset token.

**Request Body:**
```json
{
  "token": "string",
  "password": "string"
}
```

**Response:**
```json
{
  "message": "Password has been reset."
}
```

---

### `POST /auth/verify-email`
**Responsibility:** Verify a user's email using the verification token.

**Request Body:**
```json
{
  "token": "string"
}
```

**Response:**
```json
{
  "message": "Email verified successfully"
}
```

---

### `POST /auth/resend-verification`
**Responsibility:** Resend the email verification link to the user.

**Request Body:**
```json
{
  "email": "string"
}
```

**Response:**
```json
{
  "message": "If an account exists with that email, a verification link has been sent."
}
```

---

## Organizations (`/organizations`)

### `GET /organizations`
**Responsibility:** List all organizations the current user belongs to.

**Query Parameters:** None

**Response:** `list[OrganizationRead]`

---

### `POST /organizations`
**Responsibility:** Create a new organization and assign the current user as owner.

**Request Body:**
```json
{
  "name": "string",
  "slug": "string"
}
```

**Response:** `OrganizationRead`

---

### `GET /organizations/{org_id}`
**Responsibility:** Get a specific organization by ID.

**Path Parameters:**
- `org_id` (UUID)

**Response:** `OrganizationRead`

---

### `PATCH /organizations/{org_id}`
**Responsibility:** Update an organization's details.

**Path Parameters:**
- `org_id` (UUID)

**Request Body:**
```json
{
  "name": "string (optional)",
  "slug": "string (optional)"
}
```

**Response:** `OrganizationRead`

---

### `DELETE /organizations/{org_id}`
**Responsibility:** Delete an organization.

**Path Parameters:**
- `org_id` (UUID)

**Response:** HTTP 204 No Content

---

## Projects (`/projects`)

### `GET /projects`
**Responsibility:** List all projects in the current user's organization.

**Query Parameters:**
- `organization_id` (string, optional): Filter by organization

**Response:** `list[ProjectRead]`

---

### `POST /projects`
**Responsibility:** Create a new project within an organization.

**Request Body:**
```json
{
  "name": "string",
  "slug": "string",
  "description": "string (optional)",
  "organization_id": "UUID (optional)",
  "preset": "string (optional)",
  "settings": "object (optional)"
}
```

**Response:** `ProjectRead`

---

### `GET /projects/{project_id}`
**Responsibility:** Get a specific project by ID.

**Path Parameters:**
- `project_id` (UUID)

**Response:** `ProjectRead`

---

### `PATCH /projects/{project_id}`
**Responsibility:** Update a project's details.

**Path Parameters:**
- `project_id` (UUID)

**Request Body:**
```json
{
  "name": "string (optional)",
  "slug": "string (optional)",
  "description": "string (optional)",
  "settings": "object (optional)"
}
```

**Response:** `ProjectRead`

---

### `DELETE /projects/{project_id}`
**Responsibility:** Delete a project.

**Path Parameters:**
- `project_id` (UUID)

**Response:** HTTP 204 No Content

---

## Runtimes (`/runtimes`)

### `GET /runtimes`
**Responsibility:** List runtimes. Can filter by `project_id` or `organization_id`.

**Query Parameters:**
- `project_id` (string, optional)
- `organization_id` (string, optional)

**Response:** `list[RuntimeRead]`

---

### `POST /runtimes`
**Responsibility:** Create or get an existing runtime for a project.

**Request Body:**
```json
{
  "project_id": "UUID",
  "provider": "string (optional)",
  "model": "string (optional)",
  "embedding_model": "string (optional)",
  "vector_store": "string (optional)",
  "chunk_size": "integer (optional)",
  "chunk_overlap": "integer (optional)"
}
```

**Response:** `RuntimeRead`

---

### `GET /runtimes/{runtime_id}`
**Responsibility:** Get a specific runtime by ID.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** `RuntimeRead`

---

### `GET /runtimes/project/{project_id}`
**Responsibility:** Get the runtime for a specific project.

**Path Parameters:**
- `project_id` (UUID)

**Response:** `RuntimeRead`

---

### `PATCH /runtimes/{runtime_id}`
**Responsibility:** Update runtime configuration.

**Path Parameters:**
- `runtime_id` (UUID)

**Request Body:**
```json
{
  "provider": "string (optional)",
  "model": "string (optional)",
  "embedding_model": "string (optional)",
  "vector_store": "string (optional)",
  "chunk_size": "integer (optional)",
  "chunk_overlap": "integer (optional)"
}
```

**Response:** `RuntimeRead`

---

### `POST /runtimes/{runtime_id}/rebuild`
**Responsibility:** Enqueue a full runtime rebuild (re-indexes all documents).

**Path Parameters:**
- `runtime_id` (UUID)

**Response:**
```json
{
  "runtime_id": "UUID",
  "status": "queued",
  "trigger": "manual"
}
```

---

### `POST /runtimes/{runtime_id}/propagate`
**Responsibility:** Enqueue runtime propagation to vector store.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** `dict`

---

### `POST /runtimes/{runtime_id}/cancel`
**Responsibility:** Cancel a running or queued runtime build.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** `dict`

---

### `GET /runtimes/{runtime_id}/health`
**Responsibility:** Get runtime health metrics and status.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** `RuntimeHealthResponse`

---

### `GET /runtimes/{runtime_id}/metrics`
**Responsibility:** Get runtime metrics summary for a time window.

**Path Parameters:**
- `runtime_id` (UUID)

**Query Parameters:**
- `hours` (integer, 1-168, default: 24)

**Response:** `dict`

---

### `GET /runtimes/{runtime_id}/logs`
**Responsibility:** Get build logs for a runtime.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** `list[RuntimeBuildLogRead]`

---

### `GET /runtimes/{runtime_id}/chunks`
**Responsibility:** Get build chunks for a runtime.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** `list[RuntimeBuildChunkRead]`

---

### `DELETE /runtimes/{runtime_id}`
**Responsibility:** Delete a runtime.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** HTTP 204 No Content

---

## Knowledge (`/knowledge`)

### `GET /knowledge?project_id={id}`
**Responsibility:** List knowledge bases for a project.

**Query Parameters:**
- `project_id` (string, required)

**Response:** `list[KnowledgeBaseRead]`

---

### `POST /knowledge`
**Responsibility:** Create a new knowledge base.

**Request Body:**
```json
{
  "project_id": "UUID",
  "name": "string",
  "description": "string (optional)",
  "config": "object (optional)"
}
```

**Response:** `KnowledgeBaseRead`

---

### `POST /knowledge/documents`
**Responsibility:** Create a document record with text content (JSON).

**Request Body:**
```json
{
  "title": "string",
  "content": "string (optional)",
  "source": "string (optional)",
  "knowledge_base_id": "UUID"
}
```

**Response:** `DocumentRead`

**Note:** Use `/documents/upload` for binary files (PDF, DOCX, etc.).

---

### `POST /knowledge/documents/upload`
**Responsibility:** Upload a document file (multipart/form-data or JSON with base64).

**Request (multipart/form-data):**
- `file` (binary, required)
- `title` (string, required)
- `knowledge_base_id` (string, required)
- `source` (string, optional)

**Response:** `DocumentRead`

---

### `GET /knowledge/{knowledge_base_id}/documents`
**Responsibility:** List documents in a knowledge base.

**Path Parameters:**
- `knowledge_base_id` (UUID)

**Response:** `list[DocumentRead]`

---

### `GET /knowledge/sources?project_id={id}`
**Responsibility:** List knowledge sources for a project.

**Query Parameters:**
- `project_id` (string, required)

**Response:** `list[KnowledgeSourceRead]`

---

### `POST /knowledge/sources`
**Responsibility:** Create a new knowledge source connection.

**Request Body:**
```json
{
  "project_id": "UUID",
  "source_type": "github | notion | gdrive | crawler | database",
  "display_name": "string",
  "config": "object",
  "sync_frequency": "string (optional, default: manual)"
}
```

**Response:** `KnowledgeSourceRead`

---

### `PATCH /knowledge/sources/{source_id}`
**Responsibility:** Update a knowledge source.

**Path Parameters:**
- `source_id` (UUID)

**Request Body:**
```json
{
  "display_name": "string (optional)",
  "config": "object (optional)",
  "sync_frequency": "string (optional)",
  "is_active": "boolean (optional)"
}
```

**Response:** `KnowledgeSourceRead`

---

### `DELETE /knowledge/sources/{source_id}`
**Responsibility:** Delete a knowledge source.

**Path Parameters:**
- `source_id` (UUID)

**Response:** HTTP 204 No Content

---

### `POST /knowledge/test-connection`
**Responsibility:** Test a knowledge source connection.

**Request Body:**
```json
{
  "source_id": "UUID"
}
```

**Response:**
```json
{
  "success": true,
  "message": "string"
}
```

---

### `POST /knowledge/discover`
**Responsibility:** Discover metadata from a knowledge source.

**Request Body:**
```json
{
  "source_id": "UUID"
}
```

**Response:** `dict`

---

### `POST /knowledge/sources/{source_id}/sync`
**Responsibility:** Trigger a sync job for a knowledge source.

**Path Parameters:**
- `source_id` (UUID)

**Response:** `SyncJobRead`

---

### `GET /knowledge/sources/{source_id}/sync-jobs`
**Responsibility:** List sync jobs for a knowledge source.

**Path Parameters:**
- `source_id` (UUID)

**Response:** `list[SyncJobRead]`

---

### `GET /knowledge/sync-jobs/{job_id}`
**Responsibility:** Get a specific sync job.

**Path Parameters:**
- `job_id` (UUID)

**Response:** `SyncJobRead`

---

### `POST /knowledge/sync-jobs/{job_id}/cancel`
**Responsibility:** Cancel a running sync job.

**Path Parameters:**
- `job_id` (UUID)

**Response:** `SyncJobRead`

---

## Providers (`/providers`)

### `POST /providers/test-connection`
**Responsibility:** Test a provider connection (OpenAI, Anthropic, etc.).

**Request Body:**
```json
{
  "provider_name": "string",
  "api_key": "string"
}
```

**Response:**
```json
{
  "success": true,
  "message": "string"
}
```

---

### `POST /providers/discover`
**Responsibility:** Discover available models from a provider.

**Request Body:**
```json
{
  "provider_name": "string",
  "api_key": "string"
}
```

**Response:** `dict`

---

### `POST /providers/{connection_id}/sync`
**Responsibility:** Sync provider models to the local cache.

**Path Parameters:**
- `connection_id` (UUID)

**Response:** `dict`

---

### `POST /providers/{connection_id}/refresh`
**Responsibility:** Refresh provider connection status.

**Path Parameters:**
- `connection_id` (UUID)

**Response:** `dict`

---

### `GET /providers/{connection_id}/health`
**Responsibility:** Check provider connection health.

**Path Parameters:**
- `connection_id` (UUID)

**Response:** `dict`

---

### `GET /providers`
**Responsibility:** List all provider connections.

**Response:** `list[ProviderConnectionRead]`

---

### `GET /providers/with-models`
**Responsibility:** List provider connections with their available models.

**Response:** `list[dict]`

---

### `POST /providers`
**Responsibility:** Create a new provider connection.

**Request Body:**
```json
{
  "provider_name": "string",
  "display_name": "string",
  "api_key": "string",
  "config": "object (optional)"
}
```

**Response:** `ProviderConnectionRead`

---

### `PATCH /providers/{connection_id}`
**Responsibility:** Update a provider connection.

**Path Parameters:**
- `connection_id` (UUID)

**Request Body:**
```json
{
  "display_name": "string (optional)",
  "api_key": "string (optional)",
  "config": "object (optional)",
  "is_active": "boolean (optional)"
}
```

**Response:** `ProviderConnectionRead`

---

### `DELETE /providers/{connection_id}`
**Responsibility:** Delete a provider connection.

**Path Parameters:**
- `connection_id` (UUID)

**Response:** HTTP 204 No Content

---

## Tools (`/tools`)

### `GET /tools`
**Responsibility:** List tools for a project.

**Query Parameters:**
- `project_id` (string, optional)

**Response:** `list[ToolRead]`

---

### `POST /tools`
**Responsibility:** Create a new tool.

**Request Body:**
```json
{
  "project_id": "UUID",
  "name": "string",
  "description": "string (optional)",
  "schema": "object",
  "implementation": "string"
}
```

**Response:** `ToolRead`

---

### `PATCH /tools/{tool_id}`
**Responsibility:** Update a tool.

**Path Parameters:**
- `tool_id` (UUID)

**Request Body:**
```json
{
  "name": "string (optional)",
  "description": "string (optional)",
  "schema": "object (optional)",
  "implementation": "string (optional)"
}
```

**Response:** `ToolRead`

---

### `DELETE /tools/{tool_id}`
**Responsibility:** Delete a tool.

**Path Parameters:**
- `tool_id` (UUID)

**Response:** HTTP 204 No Content

---

## Chat Completions (`/chat`)

### `POST /chat/completions`
**Responsibility:** Stream chat completions from the configured runtime/LLM provider.

**Request Body:**
```json
{
  "messages": "array",
  "model": "string (optional)",
  "stream": "boolean (optional)"
}
```

**Response:** Streaming JSON (Server-Sent Events)

---

## Invoke (`/invoke`)

### `POST /invoke`
**Responsibility:** Invoke a model through the router with automatic provider fallback.

**Request Body:**
```json
{
  "model": "string",
  "messages": "array",
  "provider": "string (optional)",
  "stream": "boolean (optional)"
}
```

**Response:** `InvokeResponse`

---

## Router (`/router`)

### `GET /router/models`
**Responsibility:** Get available models from all configured providers.

**Query Parameters:**
- `provider` (string, optional): Filter by provider

**Response:** `list[dict]`

---

### `POST /router/recommend`
**Responsibility:** Get model recommendations based on a prompt.

**Request Body:**
```json
{
  "prompt": "string",
  "constraints": "object (optional)"
}
```

**Response:** `dict`

---

## Models (`/models`)

### `GET /models`
**Responsibility:** List all registered models.

**Query Parameters:**
- `provider` (string, optional)
- `family` (string, optional)

**Response:** `list[ModelInfo]`

---

### `GET /models/providers`
**Responsibility:** List all model providers.

**Response:** `list[ModelProvider]`

---

### `GET /models/{model_id}`
**Responsibility:** Get a specific model by ID.

**Path Parameters:**
- `model_id` (UUID)

**Response:** `ModelInfo`

---

### `POST /models/test`
**Responsibility:** Test a model connection with a sample prompt.

**Request Body:**
```json
{
  "model_id": "UUID",
  "prompt": "string (optional)"
}
```

**Response:** `ModelTestResult`

---

### `POST /models/refresh`
**Responsibility:** Refresh the model catalog from providers.

**Request Body:** Empty

**Response:** `ModelRefreshResponse`

---

## Billing (`/billing`)

### `GET /billing`
**Responsibility:** Get current user's wallet balance.

**Response:** `WalletRead`

---

### `GET /billing/transactions`
**Responsibility:** Get wallet transaction history.

**Query Parameters:**
- `limit` (integer, optional)
- `offset` (integer, optional)

**Response:** `list[WalletTransactionRead]`

---

### `POST /billing/add-credits`
**Responsibility:** Create a checkout session for adding credits.

**Request Body:**
```json
{
  "amount": "number",
  "currency": "string (optional, default: usd)"
}
```

**Response:** `CheckoutSessionResponse`

---

### `POST /billing/refund`
**Responsibility:** Request a refund for a transaction.

**Request Body:**
```json
{
  "transaction_id": "UUID",
  "reason": "string (optional)"
}
```

**Response:** `WalletTransactionRead`

---

### `GET /billing/usage`
**Responsibility:** Get usage summary for the current billing period.

**Response:** `UsageSummary`

---

### `GET /billing/usage/logs`
**Responsibility:** Get detailed usage logs.

**Query Parameters:**
- `limit` (integer, optional)
- `offset` (integer, optional)

**Response:** `list[UsageLogRead]`

---

### `GET /billing/pricing`
**Responsibility:** Get pricing rules for all providers/models.

**Response:** `list[PricingRuleRead]`

---

### `POST /billing/estimate`
**Responsibility:** Estimate cost for a request.

**Request Body:**
```json
{
  "provider": "string",
  "model": "string",
  "input_tokens": "integer",
  "output_tokens": "integer"
}
```

**Response:** `EstimateCostResponse`

---

### `GET /billing/budget`
**Responsibility:** Get current budget settings.

**Response:** `BudgetRead | null`

---

### `PUT /billing/budget`
**Responsibility:** Update budget settings.

**Request Body:**
```json
{
  "monthly_limit": "number",
  "warning_80_sent": "boolean (optional)",
  "warning_90_sent": "boolean (optional)",
  "limit_reached": "boolean (optional)"
}
```

**Response:** `BudgetRead`

---

### `POST /billing/budget`
**Responsibility:** Create a new budget.

**Request Body:**
```json
{
  "monthly_limit": "number"
}
```

**Response:** `BudgetRead`

---

### `POST /billing/bachs-webhook`
**Responsibility:** BACHS payment webhook endpoint.

**Request Body:** Raw webhook payload from BACHS

**Response:** `dict`

---

## API Keys (`/apikeys`)

### `GET /apikeys`
**Responsibility:** List API keys for the current user/org.

**Query Parameters:**
- `project_id` (string, optional)

**Response:** `list[ApiKeyRead]`

---

### `GET /apikeys/{key_id}`
**Responsibility:** Get a specific API key.

**Path Parameters:**
- `key_id` (UUID)

**Response:** `ApiKeyRead`

---

### `POST /apikeys`
**Responsibility:** Create a new API key.

**Request Body:**
```json
{
  "name": "string",
  "project_id": "UUID (optional)",
  "scopes": "array[string] (optional)"
}
```

**Response:** `ApiKeyCreateResponse`

---

### `PUT /apikeys/{key_id}/rotate`
**Responsibility:** Rotate an API key (returns new raw key once).

**Path Parameters:**
- `key_id` (UUID)

**Response:** `ApiKeyRotateResponse`

---

### `POST /apikeys/{key_id}/expire`
**Responsibility:** Set an expiration date for an API key.

**Path Parameters:**
- `key_id` (UUID)

**Request Body:**
```json
{
  "expires_at": "string (ISO datetime)"
}
```

**Response:** `ApiKeyRead`

---

### `POST /apikeys/{key_id}/revoke`
**Responsibility:** Revoke an API key.

**Path Parameters:**
- `key_id` (UUID)

**Response:** HTTP 204 No Content

---

### `DELETE /apikeys/{key_id}`
**Responsibility:** Delete an API key permanently.

**Path Parameters:**
- `key_id` (UUID)

**Response:** HTTP 204 No Content

---

### `GET /apikeys/{key_id}/usage`
**Responsibility:** Get usage statistics for an API key.

**Path Parameters:**
- `key_id` (UUID)

**Response:** `ApiKeyUsageResponse`

---

### `PUT /apikeys/{key_id}/scopes`
**Responsibility:** Update API key scopes.

**Path Parameters:**
- `key_id` (UUID)

**Request Body:**
```json
{
  "scopes": ["string"]
}
```

**Response:** `ApiKeyRead`

---

## Users (`/users`)

### `GET /users`
**Responsibility:** List users in the current organization.

**Response:** `list[UserRead]`

---

### `GET /users/{user_id}`
**Responsibility:** Get a specific user.

**Path Parameters:**
- `user_id` (UUID)

**Response:** `UserRead`

---

### `PATCH /users/{user_id}`
**Responsibility:** Update user details.

**Path Parameters:**
- `user_id` (UUID)

**Request Body:**
```json
{
  "name": "string (optional)",
  "email": "string (optional)",
  "settings": "object (optional)"
}
```

**Response:** `UserRead`

---

### `DELETE /users/{user_id}`
**Responsibility:** Delete a user.

**Path Parameters:**
- `user_id` (UUID)

**Response:** HTTP 204 No Content

---

### `GET /users/me/settings`
**Responsibility:** Get current user's settings.

**Response:** `dict`

---

### `PATCH /users/me/settings`
**Responsibility:** Update current user's settings.

**Request Body:**
```json
{
  "key": "value"
}
```

**Response:** `dict`

---

### `POST /users/me/2fa/enable`
**Responsibility:** Enable two-factor authentication.

**Request Body:** Empty

**Response:** `dict`

---

### `POST /users/me/2fa/disable`
**Responsibility:** Disable two-factor authentication.

**Request Body:** Empty

**Response:** `dict`

---

### `POST /users/me/tokens/revoke-all`
**Responsibility:** Revoke all session tokens for the current user.

**Request Body:** Empty

**Response:** HTTP 204 No Content

---

## Events (`/events`)

### `GET /events`
**Responsibility:** List events for the current organization/project.

**Query Parameters:**
- `project_id` (string, optional)
- `event_type` (string, optional)
- `limit` (integer, optional)
- `offset` (integer, optional)

**Response:** `list[EventRead]`

---

## Notifications (`/notifications`)

### `GET /notifications`
**Responsibility:** List notifications for the current user.

**Response:** `list[NotificationRead]`

---

### `PATCH /notifications/{notification_id}`
**Responsibility:** Mark a notification as read.

**Path Parameters:**
- `notification_id` (UUID)

**Request Body:**
```json
{
  "read": true
}
```

**Response:** `NotificationRead`

---

## Workflows (`/workflows`)

### `GET /workflows`
**Responsibility:** List workflows for a project.

**Query Parameters:**
- `project_id` (string, optional)

**Response:** `list[WorkflowRead]`

---

### `POST /workflows`
**Responsibility:** Create a new workflow.

**Request Body:**
```json
{
  "project_id": "UUID",
  "name": "string",
  "description": "string (optional)",
  "steps": "array"
}
```

**Response:** `WorkflowRead`

---

### `GET /workflows/{workflow_id}`
**Responsibility:** Get a specific workflow.

**Path Parameters:**
- `workflow_id` (UUID)

**Response:** `WorkflowRead`

---

### `PATCH /workflows/{workflow_id}`
**Responsibility:** Update a workflow.

**Path Parameters:**
- `workflow_id` (UUID)

**Request Body:**
```json
{
  "name": "string (optional)",
  "description": "string (optional)",
  "steps": "array (optional)"
}
```

**Response:** `WorkflowRead`

---

### `DELETE /workflows/{workflow_id}`
**Responsibility:** Delete a workflow.

**Path Parameters:**
- `workflow_id` (UUID)

**Response:** HTTP 204 No Content

---

### `POST /workflows/run`
**Responsibility:** Execute a workflow.

**Request Body:**
```json
{
  "workflow_id": "UUID",
  "input": "object (optional)"
}
```

**Response:** `WorkflowExecutionRead`

---

### `POST /workflows/validate`
**Responsibility:** Validate a workflow definition.

**Request Body:**
```json
{
  "steps": "array"
}
```

**Response:** `WorkflowValidationResult`

---

### `POST /workflows/test`
**Responsibility:** Test a workflow with sample input.

**Request Body:**
```json
{
  "workflow_id": "UUID",
  "input": "object (optional)"
}
```

**Response:** `WorkflowTestResult`

---

### `GET /workflows/{workflow_id}/executions`
**Responsibility:** Get execution history for a workflow.

**Path Parameters:**
- `workflow_id` (UUID)

**Response:** `list[WorkflowExecutionRead]`

---

## Memory (`/memory`)

### `GET /memory`
**Responsibility:** List memory records for the current user/project.

**Query Parameters:**
- `project_id` (string, optional)

**Response:** `list[MemoryRecordRead]`

---

### `POST /memory`
**Responsibility:** Create a memory record.

**Request Body:**
```json
{
  "project_id": "UUID (optional)",
  "content": "string",
  "metadata": "object (optional)"
}
```

**Response:** `MemoryRecordRead`

---

### `POST /memory/toggle`
**Responsibility:** Toggle memory feature on/off.

**Request Body:**
```json
{
  "enabled": "boolean"
}
```

**Response:** `dict`

---

## Analytics (`/analytics`)

### `GET /analytics`
**Responsibility:** List usage events.

**Query Parameters:**
- `project_id` (string, optional)
- `limit` (integer, optional)
- `offset` (integer, optional)

**Response:** `list[UsageEventRead]`

---

### `POST /analytics`
**Responsibility:** Create a usage event (internal).

**Request Body:**
```json
{
  "project_id": "UUID (optional)",
  "event_type": "string",
  "data": "object"
}
```

**Response:** `UsageEventRead`

---

### `GET /analytics/summary`
**Responsibility:** Get usage summary.

**Query Parameters:**
- `project_id` (string, optional)
- `period` (string, optional)

**Response:** `UsageSummary`

---

## Webhooks (`/webhooks`)

### `GET /webhooks`
**Responsibility:** List webhook subscriptions.

**Response:** `list[WebhookSubscriptionRead]`

---

### `POST /webhooks`
**Responsibility:** Create a webhook subscription.

**Request Body:**
```json
{
  "url": "string",
  "events": ["string"],
  "secret": "string (optional)"
}
```

**Response:** `WebhookSubscriptionRead`

---

### `DELETE /webhooks/{webhook_id}`
**Responsibility:** Delete a webhook subscription.

**Path Parameters:**
- `webhook_id` (UUID)

**Response:** HTTP 204 No Content

---

### `GET /webhooks/events`
**Responsibility:** List available webhook event types.

**Response:** `list[string]`

---

### `GET /webhooks/{webhook_id}/deliveries`
**Responsibility:** List webhook delivery attempts.

**Path Parameters:**
- `webhook_id` (UUID)

**Response:** `list[WebhookDeliveryRead]`

---

### `POST /webhooks/{webhook_id}/deliveries/{delivery_id}/replay`
**Responsibility:** Replay a failed webhook delivery.

**Path Parameters:**
- `webhook_id` (UUID)
- `delivery_id` (UUID)

**Response:** `dict`

---

## Onboarding (`/onboarding`)

### `GET /onboarding`
**Responsibility:** Get the current user's onboarding state.

**Response:** `OnboardingStateRead`

---

### `POST /onboarding`
**Responsibility:** Create or update onboarding state.

**Request Body:**
```json
{
  "step": "string",
  "data": "object (optional)"
}
```

**Response:** `OnboardingStateRead`

---

### `PATCH /onboarding/{state_id}`
**Responsibility:** Update a specific onboarding state.

**Path Parameters:**
- `state_id` (UUID)

**Request Body:**
```json
{
  "step": "string",
  "completed": "boolean (optional)",
  "data": "object (optional)"
}
```

**Response:** `OnboardingStateRead`

---

## Runtime Assistant (`/runtime-assistant`)

### `POST /runtime-assistant/chat`
**Responsibility:** Chat with the AI runtime assistant.

**Request Body:**
```json
{
  "runtime_id": "UUID",
  "message": "string",
  "context": "object (optional)"
}
```

**Response:** `AssistantChatResponse`

---

### `GET /runtime-assistant/{runtime_id}/summary`
**Responsibility:** Get AI-generated runtime health summary.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** `dict`

---

### `GET /runtime-assistant/{runtime_id}/history`
**Responsibility:** Get chat history with the runtime assistant.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** `list[dict]`

---

### `GET /runtime-assistant/{runtime_id}/diagnostics`
**Responsibility:** Get AI diagnostics for a runtime.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** `dict`

---

### `GET /runtime-assistant/{runtime_id}/recommendations`
**Responsibility:** Get AI recommendations for runtime optimization.

**Path Parameters:**
- `runtime_id` (UUID)

**Response:** `dict`

---

## Logs (`/logs`)

### `GET /logs`
**Responsibility:** List request logs for the current user/project.

**Query Parameters:**
- `project_id` (string, optional)
- `limit` (integer, optional)
- `offset` (integer, optional)

**Response:** `list[RequestLogRead]`

---

## Embeddings (`/embeddings`)

### `POST /embeddings`
**Responsibility:** Generate embeddings for text input.

**Request Body:**
```json
{
  "text": "string",
  "model": "string (optional)"
}
```

**Response:** `EmbeddingResponse`

---

## Users (Admin) (`/admin/users`)

> Requires admin privileges.

### `GET /admin/users`
**Responsibility:** List all users (admin).

**Query Parameters:**
- `organization_id` (string, optional)
- `limit` (integer, optional)
- `offset` (integer, optional)

**Response:** `list[AdminUserRead]`

---

### `GET /admin/users/{user_id}`
**Responsibility:** Get a specific user (admin).

**Path Parameters:**
- `user_id` (UUID)

**Response:** `AdminUserRead`

---

### `PATCH /admin/users/{user_id}`
**Responsibility:** Update user details (admin).

**Path Parameters:**
- `user_id` (UUID)

**Request Body:**
```json
{
  "name": "string (optional)",
  "email": "string (optional)",
  "is_active": "boolean (optional)",
  "is_superuser": "boolean (optional)"
}
```

**Response:** `AdminUserRead`

---

### `DELETE /admin/users/{user_id}`
**Responsibility:** Delete a user (admin).

**Path Parameters:**
- `user_id` (UUID)

**Response:** HTTP 204 No Content

---

## Health (`/health`)

### `GET /health`
**Responsibility:** Public health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "version": "string",
  "timestamp": "string"
}
```

---

## Admin Health (`/admin/health`)

> Requires admin privileges.

### `GET /admin/health`
**Responsibility:** Detailed system health check.

**Response:** `dict`

---

## Admin Provider Health (`/admin/health/providers`)

> Requires admin privileges.

### `GET /admin/health/providers`
**Responsibility:** Check health of all provider connections.

**Response:** `dict`

---

## Notes

- All authenticated endpoints return `401 Unauthorized` if the session token is missing, invalid, or expired.
- All mutating endpoints (POST, PATCH, DELETE) return `403 Forbidden` if the user lacks permissions.
- UUID parameters must be valid UUID strings.
- All timestamps are ISO 8601 with timezone info.
- The API uses snake_case for internal field names; some responses may use camelCase depending on the schema.

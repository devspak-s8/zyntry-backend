# Zyntry backend architecture

## Runtime request flow

```text
HTTP/WebSocket
    -> middleware (CORS, CSRF, security headers, request context, rate limits)
    -> versioned API router
    -> dependency authorization (user, organization, project, runtime, API key)
    -> application service / UnitOfWork
    -> repositories and connector/provider adapters
    -> Postgres, Redis, external providers
```

Routers own transport concerns: parsing requests, authentication dependencies,
status codes, and response schemas. Services own use cases and policy. Repositories
own database access. Connectors and model providers own external protocols and
must report an explicit unsupported or unavailable state rather than a false
success.

## Runtime invocation boundaries

The invoke endpoint is the control-plane boundary for a runtime request. It is
responsible for authorization, budget reservation, routing, tool policy,
provider execution, persistence, and telemetry. Small request contracts and
read-only projections live in `app/services/invoke_support.py` and
`app/services/runtime_topology.py` so they can also be used by workers and
contract tests.

All writes must pass through the action permission and confirmation path. A
provider response is not considered successful until the adapter returns a
valid response and the result is persisted with its request identifier.

## Configuration and lifecycle

`app/core/config.py` is the source of truth for environment settings and
startup validation. `app/core/lifecycle.py` composes cache initialization,
idempotent catalog seeding, and the runtime event consumer. Alembic owns
production schema changes; `AUTO_CREATE_TABLES` is intended only for local
development.

## Onboarding session boundaries

The onboarding API resumes the latest active session only when no new initial
prompt is supplied, or when the supplied prompt is identical to the saved one.
A different initial prompt automatically cancels the stale active draft and
starts a new session. Clients can also call `POST /api/v1/onboarding/reset`
before starting over. Explicit statements such as “no direct integrations”
clear connectors from the draft; names and application requirements are kept
in the typed configuration and runtime plan.

## Data and tenant boundaries

Every project/runtime/API-key lookup must verify organization ownership before
reading or mutating records. Secrets are encrypted at rest and redacted from
API responses and logs. Conversation and retrieval data must retain project
and user scope when persisted.

## Change guidelines

1. Add or update a service contract before adding a route branch.
2. Keep external calls behind an adapter with typed success/error outcomes.
3. Add a unit test for policy and an opt-in integration contract for the real
   dependency.
4. Include a migration for every schema change; do not use `create_all()` in
   production.
5. Run the release checks from the runbook before merging to `main`.

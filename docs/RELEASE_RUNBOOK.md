# Zyntry release runbook

## Pre-merge checks

Run these commands from a clean checkout:

```bash
python --version                 # must match the Docker and CI version
python -m pip install -r requirements.lock
python -m compileall -q app
ruff check app scripts --select E9,F63,F7,F821
ruff check app scripts
mypy app --exclude 'app[\\/]tests'
pytest -q
alembic check
alembic heads                   # exactly one expected head
```

Run infrastructure contracts in a private test environment, never against
production:

```bash
RUN_INTEGRATION_TESTS=1 \
TEST_POSTGRES_URL='postgresql://...' \
TEST_REDIS_URL='redis://...' \
TEST_PROVIDER=google \
TEST_PROVIDER_MODEL=gemini-2.5-flash \
TEST_PROVIDER_API_KEY='...' \
pytest -m integration -q
```

Provider contract tests make a real health check and one small completion, so
use a restricted test account and a model with an enforced spend limit.

CI blocks the configured Ruff rules and application mypy contract before an
image can be built. Test fixtures are excluded from the deployment type check;
they remain covered by the normal pytest suite.

## Migration and deployment

1. Review the migration and confirm `alembic heads` has one head.
2. Build the image from the commit SHA and scan it with Trivy.
3. Back up Postgres before deployment.
4. Deploy the exact SHA-pinned image to staging.
5. Run `/health`, authentication, project/runtime access, and one read-only
   invoke smoke test.
6. Confirm worker, beat, realtime, and runtime-assistant containers are healthy.
7. Promote the same image to production.
8. Verify logs, error rate, latency, provider health, and queue depth.

The API entrypoint runs `alembic upgrade head` before starting Uvicorn. Do not
run ad-hoc schema creation in a production container. If health checks fail,
stop promotion, preserve the deployment logs and database backup, and roll back
to the previous image SHA. Investigate migrations separately before retrying.

## Required production configuration

At minimum, production must provide non-default values for `DATABASE_URL`,
`SECRET_KEY`, `JWT_SECRET`, and `ENCRYPTION_KEY`, plus the credentials required
by each enabled model provider and OAuth integration. Keep secrets in the
deployment secret store; do not commit `.env` files or place credentials in
client-side configuration.

## Incident response

- Disable the affected provider or integration before changing routing.
- Preserve the request ID and runtime ID from logs.
- Revoke exposed API keys immediately and rotate the encryption/key material if
  a secret may have been logged.
- If Redis is unavailable, verify the documented rate-limit/security fallback
  behavior and confirm no write actions are being executed without confirmation.
- Record the root cause, affected migrations/configuration, and rollback result
  in the release incident log.

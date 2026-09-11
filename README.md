# Zyntry Backend

AI Backend Platform providing a single API to orchestrate LLM providers, knowledge
retrieval (RAG), session memory, tool calling, workflow execution, model
routing, billing, webhooks, events, and runtime management.

## Tech Stack

- Python 3.13
- FastAPI
- SQLAlchemy 2 (async)
- Alembic
- PostgreSQL + pgvector
- Redis
- Celery
- Pydantic v2
- AsyncPG
- httpx

## Architecture

Clean Architecture with Dependency Injection, the Repository pattern, a service layer,
and modular feature isolation. Every feature domain under `app/api/v1` is independent.

```
app/
  api/v1/        # Routers per feature domain
  core/          # Config, settings, logging, security, db, cache, storage
  models/        # SQLAlchemy ORM models
  repositories/  # Repository pattern + Unit of Work
  services/      # Service layer
  schemas/       # Pydantic schemas
  workers/       # Celery app
  tasks/         # Celery tasks
  middleware/    # HTTP middleware
  dependencies/  # FastAPI dependencies
  prompts/       # Prompt templates
  utils/         # Shared utilities
  tests/         # Test suite
```

## Getting Started

```bash
python -m venv .venv && source .venv/bin/activate
# Use the pinned file for a reproducible production/local environment.
pip install -r requirements.lock
# requirements.txt remains the editable dependency manifest for upgrades.
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

API docs available at `http://localhost:8000/docs`.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for service boundaries and
[`docs/RELEASE_RUNBOOK.md`](docs/RELEASE_RUNBOOK.md) for quality checks,
integration contracts, migrations, and deployment procedures.

To run the default unit suite:

```bash
pytest -q
```

Real Postgres, Redis, and provider checks are opt-in and require the private
test credentials described in the release runbook:

```bash
pytest -m integration -q
```

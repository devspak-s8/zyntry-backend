# Zyntra Backend

AI Backend Platform providing a single API to orchestrate LLM providers, knowledge
retrieval (RAG), memory, tool calling, workflow execution, prompt management, model
routing, analytics, billing, and SDK support.

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
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

API docs available at `http://localhost:8000/docs`.

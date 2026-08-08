# Docker Configuration

This directory contains Docker-related configuration and helper files for the Zyntry backend.

## Contents

- `Dockerfile` - Multi-stage production Dockerfile (located at repo root)
- `.dockerignore` - Docker build ignore rules (located at repo root)
- `docker-compose.yml` - Base Docker Compose configuration (located at repo root)
- `docker-compose.prod.yml` - Production overrides (located at repo root)
- `docker-compose.dev.yml` - Development overrides (located at repo root)
- `Caddyfile` - Caddy reverse proxy configuration (located at repo root)

## Quick Reference

### Build and Start (Production)
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### Build and Start (Development)
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

### Stop Services
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

### View Logs
```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

## Directory Structure

```
.
├── Dockerfile                    # Multi-stage build
├── .dockerignore                 # Build ignore rules
├── docker-compose.yml            # Base compose
├── docker-compose.prod.yml       # Production overrides
├── docker-compose.dev.yml        # Development overrides
├── Caddyfile                     # Reverse proxy config
├── entrypoints/                  # Service entrypoint scripts
│   ├── entrypoint-api.sh
│   ├── entrypoint-worker.sh
│   ├── entrypoint-beat.sh
│   ├── entrypoint-runtime-assistant.sh
│   └── entrypoint-realtime.sh
├── healthchecks/                 # Health check scripts
│   ├── healthcheck-api.sh
│   ├── healthcheck-worker.sh
│   ├── healthcheck-redis.sh
│   ├── healthcheck-postgres.sh
│   ├── healthcheck-runtime-assistant.sh
│   └── healthcheck-realtime.sh
├── scripts/                      # Application scripts
│   ├── runtime_assistant.py      # Standalone Runtime Assistant service
│   ├── realtime.py               # Standalone Realtime service
│   └── migrate.sh                # Database migration script
├── .env.example                  # Environment variable template
└── DOCKER_DEPLOYMENT.md          # Full deployment guide
```

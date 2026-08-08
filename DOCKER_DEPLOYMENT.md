# Zyntra Backend - Docker Deployment Guide

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    AWS EC2 / Ubuntu 24.04               │
│                                                         │
│  ┌─────────┐    ┌─────────┐    ┌──────────────────┐   │
│  │ Caddy   │────│ zyntry- │    │ zyntry-realtime  │   │
│  │ :80/:443│    │ api     │    │ :8002            │   │
│  └─────────┘    └────┬────┘    └──────────────────┘   │
│       │               │                                │
│       │         ┌─────┴─────┐    ┌──────────────────┐ │
│       │         │ zyntry-   │    │ zyntry-runtime-  │ │
│       │         │ worker    │    │ assistant :8001  │ │
│       │         └─────┬─────┘    └──────────────────┘ │
│       │               │                                │
│       │         ┌─────┴─────┐                         │
│       │         │ zyntry-   │                         │
│       │         │ beat      │                         │
│       │         └─────┬─────┘                         │
│       │               │                                │
│  ┌────┴────┐   ┌─────┴─────┐   ┌─────────────────┐  │
│  │ zyntry- │   │ zyntry-   │   │    Volumes      │  │
│  │ postgres │   │ redis     │   │ (persistent)    │  │
│  └─────────┘   └───────────┘   └─────────────────┘  │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

## Services

| Service | Container | Port | Description |
|---------|-----------|------|-------------|
| API | zyntry-api | 8000 | FastAPI REST API, WebSockets, Auth, OAuth, Billing |
| Worker | zyntry-worker | - | Celery worker for background tasks |
| Beat | zyntry-beat | - | Celery beat scheduler |
| Runtime Assistant | zyntry-runtime-assistant | 8001 | Runtime chat, recommendations, optimization |
| Realtime | zyntry-realtime | 8002 | WebSocket broadcasting, events, notifications |
| PostgreSQL | zyntry-postgres | 5432 | Primary database |
| Redis | zyntry-redis | 6379 | Cache, broker, Pub/Sub |
| Caddy | zyntry-caddy | 80/443 | Reverse proxy, HTTPS, WebSocket |

## Quick Start

### Prerequisites

- Docker Engine 24.0+
- Docker Compose v2.20+
- Ubuntu 24.04 (for production)

### 1. Clone the Repository

```bash
git clone <repository-url> zyntry-backend
cd zyntry-backend
```

### 2. Configure Environment

```bash
cp .env.example .env
```

Edit `.env` and set:
- `SECRET_KEY` - Generate a secure random string
- `JWT_SECRET` - Generate a secure random string
- `ENCRYPTION_KEY` - Generate a secure 32-byte key
- `POSTGRES_PASSWORD` - Secure database password
- `DOMAIN` - Your domain (e.g., zyntry.space)
- `CADDY_ADMIN_EMAIL` - Email for Caddy/Let's Encrypt notifications

```bash
# Generate secure keys
openssl rand -hex 32  # SECRET_KEY
openssl rand -hex 32  # JWT_SECRET
openssl rand -base64 32  # ENCRYPTION_KEY
```

### 3. Production Deployment

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### 4. Verify Deployment

```bash
# Check service status
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps

# Check logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

# Test API health
curl -k https://zyntry.space/health

# Test internal API health
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api curl -f http://localhost:8000/health
```

## Development

### Start Development Environment

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

### View Logs

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f api
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f worker
```

### Run Migrations

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api python scripts/migrate.sh
```

### Stop Services

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml down
```

## AWS EC2 Deployment

### 1. Provision EC2 Instance

```bash
# Recommended instance: t3.large or larger
# OS: Ubuntu 24.04
# Storage: 30GB+ gp3
# Security Group: Open ports 22, 80, 443
```

### 2. Install Docker

```bash
# Update packages
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sh
sudo systemctl enable docker
sudo systemctl start docker

# Install Docker Compose
sudo apt install docker-compose-plugin -y
```

### 3. Clone and Deploy

```bash
git clone <repository-url> zyntry-backend
cd zyntry-backend
cp .env.example .env
# Edit .env with production values
nano .env

# Deploy
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### 4. Configure Domain

```bash
# Point your domain (e.g., zyntry.space) to the EC2 public IP
# Ensure ports 80 and 443 are open in the security group
```

### 5. SSL Certificates

Caddy automatically provisions Let's Encrypt certificates. Ensure:
- Port 80 and 443 are open in the EC2 security group
- The domain is pointed to the EC2 public IP
- Wait a few minutes for certificate provisioning

## Commands Reference

### Production

```bash
# Build and start all services
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# Stop all services
docker compose -f docker-compose.yml -f docker-compose.prod.yml down

# Stop and remove volumes (⚠️ deletes database data)
docker compose -f docker-compose.yml -f docker-compose.prod.yml down -v

# Restart all services
docker compose -f docker-compose.yml -f docker-compose.prod.yml restart

# Rebuild after code changes
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

# View logs (all services)
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f

# View logs for a specific service
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f api

docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f worker

docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f realtime

docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f runtime-assistant
```

### Development

```bash
# Build and start
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Stop
docker compose -f docker-compose.yml -f docker-compose.dev.yml down

# Stop and remove volumes
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v

# Restart
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart

# Logs
docker compose -f docker-compose.yml -f docker-compose.dev.yml logs -f
```

### Individual Service Management

```bash
# Start a service
docker compose start api
docker compose start worker
docker compose start realtime
docker compose start runtime-assistant

# Stop a service
docker compose stop api
docker compose stop worker
docker compose stop realtime
docker compose stop runtime-assistant

# Restart a service
docker compose restart api
docker compose restart worker
docker compose restart realtime
docker compose restart runtime-assistant
```

### Shell Access

```bash
# API
docker compose exec api bash

# Worker
docker compose exec worker bash

# PostgreSQL
docker compose exec postgres psql -U postgres

# Redis
docker compose exec redis redis-cli
```

### Database

```bash
# Run Alembic migrations
docker compose exec api alembic upgrade head

# Create a migration
docker compose exec api alembic revision --autogenerate -m "migration_name"
```

### Cleanup

```bash
# Remove unused images
docker image prune -a

# Remove unused containers
docker container prune

# Remove unused volumes
docker volume prune

# Remove everything unused
docker system prune -a
```

### Production Deployment Workflow

```bash
git pull

docker compose -f docker-compose.yml -f docker-compose.prod.yml down

docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

## Volumes

| Volume | Purpose |
|--------|---------|
| `postgres-data` | PostgreSQL database files |
| `redis-data` | Redis persistence |
| `uploads` | User uploaded files |
| `logs` | Application logs |
| `runtime-artifacts` | Runtime build artifacts |
| `embeddings` | Vector embeddings |
| `beat-data` | Celery Beat schedule data |
| `caddy-data` | Caddy certificates |
| `caddy-config` | Caddy configuration |

## Health Checks

All services include health checks:

```bash
# API
curl -f http://localhost:8000/health

# Runtime Assistant
curl -f http://localhost:8001/health

# Realtime
curl -f http://localhost:8002/health

# Worker
docker compose exec worker celery -A app.workers.celery_app inspect ping

# Redis
docker compose exec redis redis-cli ping

# PostgreSQL
docker compose exec postgres pg_isready -U zyntra -d zyntra
```

## Troubleshooting

### Services not starting

```bash
# Check logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs

# Check service status
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
```

### Database connection issues

```bash
# Check PostgreSQL is running
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres pg_isready

# Check environment variables
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api env | grep DATABASE
```

### Redis connection issues

```bash
# Check Redis is running
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec redis redis-cli ping

# Check environment variables
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec api env | grep REDIS
```

### SSL Certificate Issues

```bash
# Check Caddy logs
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs caddy

# Verify domain is pointing correctly
nslookup zyntry.space

# Check security group allows 80 and 443
```

## Environment Variables

See `.env.example` for the complete list of environment variables.

### Required Variables

- `SECRET_KEY` - Application secret key
- `JWT_SECRET` - JWT signing secret
- `ENCRYPTION_KEY` - Data encryption key
- `POSTGRES_PASSWORD` - Database password
- `DOMAIN` - Primary domain (for Caddy SSL)
- `CADDY_ADMIN_EMAIL` - Email for Let's Encrypt

### Optional Variables

- `OPENAI_API_KEY` - OpenAI API key
- `ANTHROPIC_API_KEY` - Anthropic API key
- `GOOGLE_API_KEY` - Google/Gemini API key
- `DEEPSEEK_API_KEY` - DeepSeek API key
- `STRIPE_SECRET_KEY` - Stripe payment key
- `SMTP_HOST` - Email server host
- `SENTRY_DSN` - Sentry error tracking

## Security

- All services run as non-root user (`appuser`)
- Redis and PostgreSQL are not exposed externally
- PostgreSQL has a shared memory limit of 256MB
- Containers run with `restart: unless-stopped`
- Caddy handles HTTPS with automatic certificate renewal
- Security headers are configured in Caddyfile
- Sensitive data should be stored in environment variables or secrets

## Monitoring

### Health Endpoints

```bash
# API
GET /health

# Runtime Assistant
GET /health

# Realtime
GET /health
```

### Logs

Logs are persisted to Docker volumes and can be accessed via:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f
```

### Metrics (Optional)

Enable Prometheus metrics by setting `PROMETHEUS_ENABLED=true` in `.env`.

## Backup

### Database Backup

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec postgres pg_dump -U zyntra zyntra > backup_$(date +%Y%m%d).sql
```

### Restore Database

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec -T postgres psql -U zyntra zyntra < backup_20240101.sql
```

### Volume Backup

```bash
docker run --rm -v zyntry-postgres-data:/data -v $(pwd):/backup alpine tar cvf /backup/postgres-backup.tar /data
```

## Updates

### Update Application Code

```bash
git pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

### Update Docker Images

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

## License

Proprietary - Zyntra Backend

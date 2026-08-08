#!/bin/bash
set -euo pipefail

echo "=========================================="
echo "Zyntry Celery Worker Starting..."
echo "=========================================="

# Wait for Redis
echo "Waiting for Redis..."
until redis-cli -h "${REDIS_HOST:-redis}" -p "${REDIS_PORT:-6379}" ping &>/dev/null; do
    echo "Redis is not ready yet..."
    sleep 2
done
echo "Redis is ready!"

# Wait for PostgreSQL
echo "Waiting for PostgreSQL..."
until pg_isready -h "${POSTGRES_HOST:-postgres}" -p "${POSTGRES_PORT:-5432}" -U "${POSTGRES_USER:-zyntra}" -d "${POSTGRES_DB:-zyntra}" &>/dev/null; do
    echo "PostgreSQL is not ready yet..."
    sleep 2
done
echo "PostgreSQL is ready!"

echo "=========================================="
echo "Starting Celery Worker..."
echo "=========================================="

exec celery -A app.workers.celery_app worker --loglevel=${LOG_LEVEL:-info} "$@"

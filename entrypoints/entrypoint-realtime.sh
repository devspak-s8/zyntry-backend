#!/bin/bash
set -euo pipefail

echo "=========================================="
echo "Zyntry Realtime Service Starting..."
echo "=========================================="

# Wait for Redis
echo "Waiting for Redis..."
until redis-cli -h "${REDIS_HOST:-redis}" -p "${REDIS_PORT:-6379}" ping &>/dev/null; do
    echo "Redis is not ready yet..."
    sleep 2
done
echo "Redis is ready!"

echo "=========================================="
echo "Starting Realtime Service..."
echo "=========================================="

exec python scripts/realtime.py "$@"

#!/bin/bash
set -euo pipefail

# Redis Health Check
# Returns 0 if healthy, 1 if unhealthy

REDIS_HOST="${REDIS_HOST:-localhost}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

if [ -n "$REDIS_PASSWORD" ]; then
    response=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" -a "$REDIS_PASSWORD" ping 2>/dev/null || echo "FAIL")
else
    response=$(redis-cli -h "$REDIS_HOST" -p "$REDIS_PORT" ping 2>/dev/null || echo "FAIL")
fi

if [ "$response" = "PONG" ]; then
    echo "Redis is healthy"
    exit 0
else
    echo "Redis is unhealthy"
    exit 1
fi

#!/bin/bash
set -euo pipefail

# Realtime Service Health Check
# Returns 0 if healthy, 1 if unhealthy

REALTIME_URL="${REALTIME_URL:-http://localhost:8002/health}"

response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$REALTIME_URL" 2>/dev/null || echo "000")

if [ "$response" = "200" ]; then
    echo "Realtime Service is healthy (HTTP $response)"
    exit 0
else
    echo "Realtime Service is unhealthy (HTTP $response)"
    exit 1
fi

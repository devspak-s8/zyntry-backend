#!/bin/bash
set -euo pipefail

# Runtime Assistant Health Check
# Returns 0 if healthy, 1 if unhealthy

RUNTIME_ASSISTANT_URL="${RUNTIME_ASSISTANT_URL:-http://localhost:8001/health}"

response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$RUNTIME_ASSISTANT_URL" 2>/dev/null || echo "000")

if [ "$response" = "200" ]; then
    echo "Runtime Assistant is healthy (HTTP $response)"
    exit 0
else
    echo "Runtime Assistant is unhealthy (HTTP $response)"
    exit 1
fi

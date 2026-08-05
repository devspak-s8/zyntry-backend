#!/bin/bash
set -euo pipefail

# API Health Check
# Returns 0 if healthy, 1 if unhealthy

API_URL="${API_URL:-http://localhost:8000/health}"

response=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$API_URL" 2>/dev/null || echo "000")

if [ "$response" = "200" ]; then
    echo "API is healthy (HTTP $response)"
    exit 0
else
    echo "API is unhealthy (HTTP $response)"
    exit 1
fi

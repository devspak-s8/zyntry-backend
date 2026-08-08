#!/bin/bash
set -euo pipefail

# Worker Health Check
# Returns 0 if healthy, 1 if unhealthy

if celery -A app.workers.celery_app inspect ping 2>/dev/null | grep -q "pong"; then
    echo "Worker is healthy"
    exit 0
else
    echo "Worker is unhealthy"
    exit 1
fi

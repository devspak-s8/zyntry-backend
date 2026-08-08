#!/bin/bash
set -euo pipefail

# PostgreSQL Health Check
# Returns 0 if healthy, 1 if unhealthy

PGHOST="${POSTGRES_HOST:-localhost}"
PGPORT="${POSTGRES_PORT:-5432}"
PGUSER="${POSTGRES_USER:-zyntra}"
PGDATABASE="${POSTGRES_DB:-zyntra}"

if pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" &>/dev/null; then
    echo "PostgreSQL is healthy"
    exit 0
else
    echo "PostgreSQL is unhealthy"
    exit 1
fi

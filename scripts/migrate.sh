#!/bin/bash
set -euo pipefail

export PYTHONPATH=/app
cd /app

echo "=========================================="
echo "Running Database Migrations..."
echo "=========================================="

alembic upgrade head

echo "=========================================="
echo "Migrations completed successfully!"
echo "=========================================="

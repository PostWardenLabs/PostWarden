#!/usr/bin/env bash
# Initialize the libro database on a local PostgreSQL (non-Docker path).
# Usage: ./scripts/init_db.sh [--with-demo]
set -euo pipefail
cd "$(dirname "$0")/.."

PSQL="psql -v ON_ERROR_STOP=1"

createdb libro 2>/dev/null || echo "database 'libro' already exists"
$PSQL -d libro -f db/schema.sql
$PSQL -d libro -f db/seed.sql
if [[ "${1:-}" == "--with-demo" ]]; then
    $PSQL -d libro -f db/seed_demo.sql
    echo "Demo entries loaded."
fi
echo "Libro database ready."

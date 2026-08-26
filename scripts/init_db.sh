#!/usr/bin/env bash
# Initialize the postwarden database on a local PostgreSQL (non-Docker path).
# Usage: ./scripts/init_db.sh [--with-demo]
set -euo pipefail
cd "$(dirname "$0")/.."

PSQL="psql -v ON_ERROR_STOP=1"

createdb postwarden 2>/dev/null || echo "database 'postwarden' already exists"
$PSQL -d postwarden -f db/schema.sql
$PSQL -d postwarden -f db/seed.sql
if [[ "${1:-}" == "--with-demo" ]]; then
    $PSQL -d postwarden -f db/seed_demo.sql
    echo "Demo entries loaded."
fi
echo "PostWarden database ready."

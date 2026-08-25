#!/usr/bin/env bash
# Create (or reset) a PostWarden login. Prompts for the password interactively
# (never as a command-line argument, so it doesn't end up in shell history).
#
# Needs DATABASE_URL pointed at a running instance — defaults to
# libro:libro@localhost:5432/libro, same as the app. Inside Docker, run it
# through the app container instead: `docker compose exec app
# python -m app.cli create-user someone`.
#
# Usage:
#   ./scripts/create_user.sh <username>            # create a new login
#   ./scripts/create_user.sh <username> --reset     # reset an existing password
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -lt 1 ]; then
    echo "Usage: $0 <username> [--reset]" >&2
    exit 1
fi

if [[ "${2:-}" == "--reset" ]]; then
    python3 -m app.cli reset-password "$1"
else
    python3 -m app.cli create-user "$1"
fi

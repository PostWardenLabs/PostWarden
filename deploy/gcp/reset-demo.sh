#!/usr/bin/env bash
# Nightly reset for demo.postwarden.org: wipes whatever visitors have done
# and reloads the seed data (db/seed.sql + db/seed_demo.sql, same as any
# fresh self-hosted install). Independent of deploy-demo.sh, which only
# updates the *code* on its own "every few weeks" cadence — this resets
# *data* every night regardless of whether the code changed.
#
# Requires LIBRO_ADMIN_USER/LIBRO_ADMIN_PASSWORD to be set in
# /opt/postwarden-demo/.env — a fresh volume is a first boot as far as the
# app is concerned, and that's the only thing that recreates the published
# demo login every time this wipes the database. Without it, demo locks
# everyone out (including you) at the next reset, seed data or not.
#
# This runs ON THE VM ITSELF via cron, not from your own machine like the
# other scripts in this directory. Installed once by hand:
#   sudo crontab -e
#   0 6 * * * /opt/postwarden-demo/deploy/gcp/reset-demo.sh >> /var/log/postwarden-demo-reset.log 2>&1
set -euo pipefail
cd /opt/postwarden-demo
docker compose down -v
docker compose up -d
echo "$(date -u +%FT%TZ) demo reset to seed data"

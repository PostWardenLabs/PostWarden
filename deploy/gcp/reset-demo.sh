#!/usr/bin/env bash
# Nightly reset for demo.postwarden.org: wipes whatever visitors have done
# and reloads the seed data (db/seed.sql + db/seed_demo.sql, same as any
# fresh self-hosted install). Independent of deploy-demo.sh, which only
# updates the *code* on its own "every few weeks" cadence — this resets
# *data* every night regardless of whether the code changed.
#
# Requires POSTWARDEN_ADMIN_USER/POSTWARDEN_ADMIN_PASSWORD to be set in
# /opt/postwarden-demo/.env — a fresh volume is a first boot as far as the
# app is concerned, and that's the only thing that recreates the published
# demo login every time this wipes the database. Without it, demo locks
# everyone out (including you) at the next reset, seed data or not.
#
# POSTWARDEN_DEMO_MODE=true should be set there too — it's what puts the
# credentials banner on the login page (see app/main.py's demo_banner
# comment). It doesn't affect the reset itself, but since this script
# recreates the container from a fresh volume every night, leaving it
# unset means the banner silently disappears at the next reset even
# though POSTWARDEN_ADMIN_USER/PASSWORD still log you in fine.
#
# This runs ON THE VM ITSELF via cron, not from your own machine like the
# other scripts in this repo — and unlike the app code, it isn't kept in
# sync by a git checkout on the VM, so it's copied over once by hand, the
# same way backup.sh already is:
#   gcloud compute scp reset-demo.sh postwarden-public:/opt/reset-demo.sh \
#     --zone=us-central1-a --project=your-project-id --tunnel-through-iap
# Then, on the VM:
#   sudo crontab -e
#   0 6 * * * /opt/reset-demo.sh >> /var/log/postwarden-demo-reset.log 2>&1
set -euo pipefail
cd /opt/postwarden-demo
docker compose down -v
docker compose up -d
echo "$(date -u +%FT%TZ) demo reset to seed data"

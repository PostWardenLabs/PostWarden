#!/usr/bin/env bash
# Redeploy beta.postwarden.org from the latest master — runs automatically
# on every push via .github/workflows/deploy-beta.yml; safe to run by hand
# too. Beta keeps its data between deploys (see deploy-demo.sh/reset-demo.sh
# for the resettable public-demo counterpart — beta is invite-only, not
# anonymous, so nothing here ever wipes its database).
# Usage: PROJECT_ID=my-project ./deploy-beta.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID, e.g. PROJECT_ID=my-project ./deploy-beta.sh}"
ZONE="${ZONE:-us-central1-a}"
VM_NAME="${VM_NAME:-postwarden-public}"

gcloud compute ssh "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" \
  --tunnel-through-iap -- '
    cd /opt/postwarden-beta &&
    sudo git fetch origin &&
    sudo git reset --hard origin/master &&
    sudo docker compose up -d --build &&
    echo "beta redeployed: $(sudo git rev-parse --short HEAD)"
  '

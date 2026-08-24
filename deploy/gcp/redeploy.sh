#!/usr/bin/env bash
# Pull the latest master and rebuild on the VM, over an IAP SSH tunnel.
# Usage: PROJECT_ID=my-project ./redeploy.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID, e.g. PROJECT_ID=my-project ./redeploy.sh}"
ZONE="${ZONE:-us-central1-a}"
VM_NAME="${VM_NAME:-libro-vm}"

gcloud compute ssh "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" \
  --tunnel-through-iap -- \
  'cd /opt/libro && sudo git fetch origin && sudo git reset --hard origin/master && sudo docker compose up -d --build && echo "Redeployed $(sudo git rev-parse --short HEAD)"'

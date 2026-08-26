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

# A brand-new identity/keypair against this VM (CI's service account, or
# your own first run) can need a few seconds longer for the guest agent to
# provision it than gcloud's own ~40s retry budget covers — gcloud says as
# much ("Try running this command again") if it happens. A cheap ping loop
# absorbs that instead of failing the real (docker-build-including) deploy.
for i in $(seq 1 6); do
  gcloud compute ssh "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" \
    --tunnel-through-iap --command "true" && break
  [ "$i" -eq 6 ] && { echo "SSH key never propagated" >&2; exit 1; }
  echo "not ready yet, retrying in 15s ($i/6)"
  sleep 15
done

gcloud compute ssh "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" \
  --tunnel-through-iap -- '
    cd /opt/postwarden-beta &&
    sudo git fetch origin &&
    sudo git reset --hard origin/master &&
    sudo docker compose up -d --build &&
    echo "beta redeployed: $(sudo git rev-parse --short HEAD)"
  '

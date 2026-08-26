#!/usr/bin/env bash
# Redeploy demo.postwarden.org from the latest git tag — a deliberate
# "stable build," not master. Run this by hand whenever you decide a
# commit is demo-worthy (cut the tag first: `git tag vX.Y.Z && git push
# --tags`), not on every push — see deploy-beta.sh for the continuously-
# deployed counterpart. This only updates the code; the nightly data reset
# is reset-demo.sh, running on the VM itself via cron, independent of this.
# Usage: PROJECT_ID=my-project ./deploy-demo.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID, e.g. PROJECT_ID=my-project ./deploy-demo.sh}"
ZONE="${ZONE:-us-central1-a}"
VM_NAME="${VM_NAME:-postwarden-public}"

gcloud compute ssh "$VM_NAME" --zone "$ZONE" --project "$PROJECT_ID" \
  --tunnel-through-iap -- '
    cd /opt/postwarden-demo &&
    sudo git fetch --tags origin &&
    LATEST_TAG=$(sudo git tag --sort=-creatordate | head -1) &&
    sudo git checkout "$LATEST_TAG" &&
    sudo docker compose up -d --build &&
    echo "demo redeployed: $LATEST_TAG"
  '

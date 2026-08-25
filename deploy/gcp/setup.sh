#!/usr/bin/env bash
# One-time provisioning for PostWarden on Google Cloud: a single Compute Engine
# VM running docker-compose, reachable ONLY through an IAP tunnel — no
# firewall rule opens the app (or SSH) to the public internet at all.
#
# Run from your own machine (needs the gcloud CLI, authenticated, with a
# project already selected: `gcloud init`). Idempotent-ish: safe to re-run,
# `gcloud ... create` calls will just fail loudly if the resource exists.
#
# Usage:
#   PROJECT_ID=my-project ./setup.sh
set -euo pipefail
cd "$(dirname "$0")"

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID, e.g. PROJECT_ID=my-project ./setup.sh}"
ZONE="${ZONE:-us-central1-a}"                 # free-tier-eligible region
VM_NAME="${VM_NAME:-libro-vm}"
NETWORK="${NETWORK:-libro-vpc}"
ACCOUNT="$(gcloud config get-value account)"

echo "== Project: $PROJECT_ID  Zone: $ZONE  Account: $ACCOUNT =="

echo "-- Ensuring a GitHub deploy key exists (the repo is private)"
if [ ! -f deploy_key ]; then
  ssh-keygen -t ed25519 -f deploy_key -N "" -C "libro-vm-deploy-key" -q
  cat <<EOF

Generated deploy_key / deploy_key.pub (gitignored — never committed).
Add the public key as a READ-ONLY deploy key before the VM's first boot,
or its git clone will fail exactly like a missing-credential error:

  https://github.com/<owner>/<repo>/settings/keys -> Add deploy key
  (leave "Allow write access" unchecked)

$(cat deploy_key.pub)

EOF
  read -r -p "Press Enter once the key is added to GitHub... "
else
  echo "   (deploy_key already exists, reusing)"
fi

echo "-- Cloudflare Tunnel token (optional — a public domain via Cloudflare"
echo "   Access; see README.md 'Public domain via Cloudflare Tunnel'. Skip"
echo "   with a blank answer if you just want the IAP-tunnel-only setup.)"
if [ ! -f cloudflare_tunnel_token ]; then
  read -r -p "Paste a Cloudflare Tunnel token, or leave blank to skip: " CF_TOKEN_INPUT
  if [ -n "$CF_TOKEN_INPUT" ]; then
    printf '%s' "$CF_TOKEN_INPUT" > cloudflare_tunnel_token
    chmod 600 cloudflare_tunnel_token
  fi
else
  echo "   (cloudflare_tunnel_token already exists, reusing)"
fi

echo "-- Enabling required APIs"
gcloud services enable compute.googleapis.com iap.googleapis.com \
  --project "$PROJECT_ID"

echo "-- Creating an isolated VPC (no implicit rules — everything is closed by default)"
gcloud compute networks create "$NETWORK" \
  --project "$PROJECT_ID" --subnet-mode=auto \
  || echo "   (network already exists, continuing)"

echo "-- Allowing SSH only from Google's IAP forwarding range"
gcloud compute firewall-rules create "${NETWORK}-allow-iap-ssh" \
  --project "$PROJECT_ID" --network "$NETWORK" \
  --direction=INGRESS --action=ALLOW --rules=tcp:22 \
  --source-ranges=35.235.240.0/20 \
  || echo "   (firewall rule already exists, continuing)"

echo "-- Allowing the app port only from Google's IAP forwarding range"
# IAP TCP forwarding still needs a firewall rule per destination port, same
# as SSH above — without this, `start-iap-tunnel ... 8000` connects but
# then fails with "failed to connect to backend".
gcloud compute firewall-rules create "${NETWORK}-allow-iap-app" \
  --project "$PROJECT_ID" --network "$NETWORK" \
  --direction=INGRESS --action=ALLOW --rules=tcp:8000 \
  --source-ranges=35.235.240.0/20 \
  || echo "   (firewall rule already exists, continuing)"

echo "-- Granting your account permission to open IAP tunnels"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="user:$ACCOUNT" --role="roles/iap.tunnelResourceAccessor" \
  --condition=None >/dev/null

METADATA_FILES="startup-script=startup-script.sh,deploy-ssh-key=deploy_key"
if [ -f cloudflare_tunnel_token ]; then
  METADATA_FILES="$METADATA_FILES,cloudflare-tunnel-token=cloudflare_tunnel_token"
fi

echo "-- Creating the VM (e2-micro — free-tier eligible in us-west1/us-central1/us-east1)"
gcloud compute instances create "$VM_NAME" \
  --project "$PROJECT_ID" --zone "$ZONE" \
  --machine-type=e2-micro \
  --image-family=debian-12 --image-project=debian-cloud \
  --boot-disk-size=20GB --boot-disk-type=pd-standard \
  --network="$NETWORK" --subnet="$NETWORK" \
  --metadata-from-file="$METADATA_FILES"

cat <<EOF

Done. The VM is booting and will build+start the app on its own
(docker install + git clone + docker compose up -d --build) — give it a
couple of minutes on first boot.

No port is open to the public internet, including the app itself. Reach it
with:
  gcloud compute start-iap-tunnel $VM_NAME 8000 \\
    --local-host-port=localhost:8000 --zone=$ZONE --project=$PROJECT_ID

then open http://localhost:8000 on your own machine. See README.md in this
directory for redeploying after a git push, connecting BI tools, and
backups.
EOF

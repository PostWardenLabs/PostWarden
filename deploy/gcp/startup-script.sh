#!/usr/bin/env bash
# GCE metadata startup-script for the Libro VM.
#
# Runs as root on every boot. Installs Docker if it isn't there yet, wires
# up the read-only GitHub deploy key from this instance's metadata, clones
# (or updates) the app over SSH, and brings it up with docker compose — the
# exact same docker-compose.yml used locally, unmodified.
set -euo pipefail

REPO_URL="git@github.com:mirelesde/libro.git"
APP_DIR="/opt/libro"
DEPLOY_KEY="/root/.ssh/libro_deploy_key"

if ! command -v docker >/dev/null 2>&1; then
  apt-get update
  apt-get install -y ca-certificates curl gnupg git
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo \
    "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

# The repo is private, so cloning needs the read-only deploy key this
# instance was created with (see setup.sh --metadata-from-file). Fetch it
# from the metadata server once and point root's SSH config at it, so this
# script, redeploy.sh, and any manual `git fetch` as root all just work —
# no GIT_SSH_COMMAND to remember to set.
mkdir -p /root/.ssh
chmod 700 /root/.ssh
if [ ! -f "$DEPLOY_KEY" ]; then
  curl -s -H "Metadata-Flavor: Google" \
    "http://metadata.google.internal/computeMetadata/v1/instance/attributes/deploy-ssh-key" \
    -o "$DEPLOY_KEY"
  chmod 600 "$DEPLOY_KEY"
fi
cat > /root/.ssh/config <<EOF
Host github.com
  IdentityFile $DEPLOY_KEY
  IdentitiesOnly yes
  StrictHostKeyChecking accept-new
EOF
chmod 600 /root/.ssh/config

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" reset --hard origin/master
else
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
docker compose up -d --build

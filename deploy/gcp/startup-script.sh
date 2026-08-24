#!/usr/bin/env bash
# GCE metadata startup-script for the Libro VM.
#
# Runs as root on every boot. Installs Docker if it isn't there yet, then
# clones (or updates) the app and brings it up with docker compose — the
# exact same docker-compose.yml used locally, unmodified.
set -euo pipefail

REPO_URL="https://github.com/mirelesde/libro.git"
APP_DIR="/opt/libro"

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

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" fetch origin
  git -C "$APP_DIR" reset --hard origin/master
else
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR"
docker compose up -d --build

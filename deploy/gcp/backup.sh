#!/usr/bin/env bash
# Optional: dump the database and upload it to a GCS bucket. Meant to run
# ON THE VM (cron or a systemd timer — see README.md "Backups"), not from
# your own machine. Requires the gcloud CLI (for gsutil) on the VM and a
# bucket the VM's service account can write to.
#
# Usage: POSTWARDEN_BACKUP_BUCKET=gs://my-postwarden-backups ./backup.sh
set -euo pipefail

BUCKET="${POSTWARDEN_BACKUP_BUCKET:?Set POSTWARDEN_BACKUP_BUCKET, e.g. gs://my-postwarden-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="/tmp/postwarden-$STAMP.sql.gz"

cd /opt/postwarden
docker compose exec -T db pg_dump -U postwarden -d postwarden | gzip > "$DUMP"
gsutil cp "$DUMP" "$BUCKET/postwarden-$STAMP.sql.gz"
rm -f "$DUMP"
echo "Backed up to $BUCKET/postwarden-$STAMP.sql.gz"

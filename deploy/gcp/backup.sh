#!/usr/bin/env bash
# Optional: dump the database and upload it to a GCS bucket. Meant to run
# ON THE VM (cron or a systemd timer — see README.md "Backups"), not from
# your own machine. Requires the gcloud CLI (for gsutil) on the VM and a
# bucket the VM's service account can write to.
#
# Usage: LIBRO_BACKUP_BUCKET=gs://my-libro-backups ./backup.sh
set -euo pipefail

BUCKET="${LIBRO_BACKUP_BUCKET:?Set LIBRO_BACKUP_BUCKET, e.g. gs://my-libro-backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DUMP="/tmp/libro-$STAMP.sql.gz"

cd /opt/libro
docker compose exec -T db pg_dump -U libro -d libro | gzip > "$DUMP"
gsutil cp "$DUMP" "$BUCKET/libro-$STAMP.sql.gz"
rm -f "$DUMP"
echo "Backed up to $BUCKET/libro-$STAMP.sql.gz"

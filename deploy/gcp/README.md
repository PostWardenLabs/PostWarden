# Deploying Libro on Google Cloud

One Compute Engine VM runs `docker-compose.yml` almost exactly as it runs
locally — app and Postgres together, same images, same schema/seed
bootstrap. No app code changes, no Cloud SQL, no load balancer.

**Access is restricted to you alone**, and not by an IP allowlist (your
home IP can change) — the VM has **no firewall rule opening anything to the
public internet, including the app itself**. You reach it exclusively
through [Identity-Aware Proxy (IAP) TCP forwarding](https://cloud.google.com/iap/docs/using-tcp-forwarding):
`gcloud` opens an authenticated tunnel from your machine to the VM's
localhost, gated by your Google IAM identity. Nobody without
`roles/iap.tunnelResourceAccessor` on the project can reach it, full stop —
not by guessing a URL, not by port-scanning the VM's IP.

## Prerequisites

- A GCP project with billing enabled ([console.cloud.google.com](https://console.cloud.google.com))
- The [gcloud CLI](https://cloud.google.com/sdk/docs/install) installed and run once: `gcloud init`
- This repo's `origin` remote public on GitHub (it already is) — the VM
  clones it directly, no deploy keys needed

## 1. Provision the VM

```bash
cd deploy/gcp
PROJECT_ID=your-project-id ./setup.sh
```

This is idempotent-ish and does, in order:

1. Enables the Compute Engine and IAP APIs
2. Creates a **dedicated VPC** (`libro-vpc`) — a network you create yourself
   starts with zero firewall rules (unlike the project's default network,
   which usually ships a permissive `default-allow-ssh` open to
   `0.0.0.0/0`). Nothing is reachable here until a rule says otherwise.
3. Adds exactly one firewall rule: allow tcp:22 from `35.235.240.0/20` —
   Google's IAP forwarding range, not the public internet
4. Grants your account `roles/iap.tunnelResourceAccessor`
5. Creates an `e2-micro` VM (free-tier eligible in `us-west1`,
   `us-central1`, `us-east1`) with [`startup-script.sh`](startup-script.sh)
   attached, which installs Docker and runs
   `docker compose up -d --build` on every boot

First boot takes a couple of minutes (Docker install + image build). Check
progress with:

```bash
gcloud compute instances get-serial-port-output libro-vm \
  --zone=us-central1-a --project=your-project-id | grep -A5 startup-script
```

## 2. Open the app

```bash
gcloud compute start-iap-tunnel libro-vm 8000 \
  --local-host-port=localhost:8000 --zone=us-central1-a --project=your-project-id
```

Leave that running and open **http://localhost:8000** — that's the real
app, tunneled from the VM. Ctrl-C the tunnel when you're done; nothing is
left listening publicly in the meantime either way.

### Connecting Power BI / Excel

The README's BI instructions still apply, but reaching Postgres takes an
**SSH** tunnel, not `start-iap-tunnel` — `docker-compose.yml` (rightly)
binds Postgres to the VM's own `127.0.0.1`, and `start-iap-tunnel` connects
to the VM's *internal network IP*, which is a different address as far as
that loopback bind is concerned; it would just refuse the connection. An
SSH port-forward runs its listener on the VM itself, so it can reach
`127.0.0.1:5432` there the same way a process on the VM would:

```bash
gcloud compute ssh libro-vm --zone=us-central1-a --project=your-project-id \
  --tunnel-through-iap -- -N -L 5432:localhost:5432
```

Leave that running and connect Power BI/Excel to `localhost:5432` exactly
as the main README describes.

## 3. Redeploy after a `git push`

The VM doesn't auto-update — it clones once at boot. To push a new commit
live:

```bash
PROJECT_ID=your-project-id ./redeploy.sh
```

(SSHes in over IAP, `git reset --hard origin/master`, rebuilds and
restarts via `docker compose up -d --build`.) Rebooting the VM has the
same effect, since `startup-script.sh` re-runs on every boot.

## 4. Backups (optional, recommended — it's real financial data)

The database lives in a Docker named volume on the VM's boot disk. That
survives reboots and redeploys, but not a deleted/recreated VM. To back up
to Cloud Storage:

```bash
gsutil mb -l us-central1 gs://your-libro-backups   # once
gcloud compute scp backup.sh libro-vm:/opt/libro/backup.sh \
  --zone=us-central1-a --project=your-project-id --tunnel-through-iap
```

Then, on the VM (`gcloud compute ssh libro-vm --tunnel-through-iap`),
install the Cloud SDK if it isn't already there and schedule
`backup.sh` daily, e.g. as a cron entry:

```
0 6 * * * LIBRO_BACKUP_BUCKET=gs://your-libro-backups /opt/libro/backup.sh
```

To restore: `gsutil cp gs://your-libro-backups/libro-<stamp>.sql.gz - | gunzip | docker compose exec -T db psql -U libro -d libro`.

## Cost

`e2-micro` + a 20GB standard persistent disk is within GCP's [always-free
tier](https://cloud.google.com/free/docs/free-cloud-features#compute) in
`us-west1`/`us-central1`/`us-east1` — realistically **$0/month** for a
personal, low-traffic ledger, plus pennies for any Cloud Storage backups.
IAP tunneling itself is free. If Postgres+app feel memory-constrained on
1GB RAM, `--machine-type=e2-small` is the next step up (no longer free,
~$12/month).

## Tearing it down

```bash
gcloud compute instances delete libro-vm --zone=us-central1-a --project=your-project-id
gcloud compute firewall-rules delete libro-vpc-allow-iap-ssh --project=your-project-id
gcloud compute networks delete libro-vpc --project=your-project-id
```

This deletes the boot disk (and the database with it) unless you took a
backup first — see step 4.

# Deploying PostWarden on Google Cloud

One Compute Engine VM runs `docker-compose.yml` almost exactly as it runs
locally — app and Postgres together, same images, same schema/seed
bootstrap. No app code changes, no Cloud SQL, no load balancer. This is
the setup for **your own instance**; `demo.postwarden.org` and
`beta.postwarden.org` are a second, separate VM with the same shape —
see "demo.postwarden.org and beta.postwarden.org" below once you've
read the rest of this as the base case.

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
- If `origin` is a **private** GitHub repo (the common case), `setup.sh`
  generates a read-only deploy keypair on first run and walks you through
  adding the public half at `github.com/<owner>/<repo>/settings/keys` — the
  VM clones over SSH using it. Nothing to do here ahead of time; the script
  pauses and asks.

## 1. Provision the VM

```bash
cd deploy/gcp
PROJECT_ID=your-project-id ./setup.sh
```

This is idempotent-ish and does, in order:

1. Generates `deploy_key`/`deploy_key.pub` if they don't exist yet
   (gitignored — never committed) and pauses for you to add the public key
   as a GitHub deploy key, read-only
2. Enables the Compute Engine and IAP APIs
3. Creates a **dedicated VPC** (`postwarden-vpc`) — a network you create yourself
   starts with zero firewall rules (unlike the project's default network,
   which usually ships a permissive `default-allow-ssh` open to
   `0.0.0.0/0`). Nothing is reachable here until a rule says otherwise.
4. Adds two firewall rules, both scoped to `35.235.240.0/20` — Google's IAP
   forwarding range, not the public internet: tcp:22 (SSH) and tcp:8000
   (the app). IAP TCP forwarding needs an explicit rule per destination
   port even though it's already identity-gated; without the second rule,
   `start-iap-tunnel ... 8000` connects but then fails with "failed to
   connect to backend"
5. Grants your account `roles/iap.tunnelResourceAccessor`
6. Creates an `e2-micro` VM (free-tier eligible in `us-west1`,
   `us-central1`, `us-east1`) with [`startup-script.sh`](startup-script.sh)
   and the deploy key attached as metadata. The startup script installs
   Docker, wires the deploy key into root's SSH config, and runs
   `docker compose up -d --build` on every boot

First boot takes a couple of minutes (Docker install + image build). Check
progress with:

```bash
gcloud compute instances get-serial-port-output postwarden-vm \
  --zone=us-central1-a --project=your-project-id | grep -A5 startup-script
```

## 2. Open the app

```bash
gcloud compute start-iap-tunnel postwarden-vm 8000 \
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
gcloud compute ssh postwarden-vm --zone=us-central1-a --project=your-project-id \
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

## Public domain via Cloudflare Tunnel (optional)

If you'd rather visit `https://postwarden.yourdomain.com` than run a `gcloud`
tunnel command, and your domain's DNS is on Cloudflare, a Cloudflare
Tunnel gets you a real domain with **zero GCP firewall changes** — the
tunnel is an outbound-only connection from the VM, so the IAP-only setup
above stays exactly as closed as it is. Access is gated by [Cloudflare
Access](https://developers.cloudflare.com/cloudflare-one/policies/access/)
(free for up to 50 users) instead of GCP IAM — a login (email code or
Google/GitHub OAuth) sits in front of the tunnel's public hostname, so the
app still never sees unauthenticated traffic.

**One-time setup, in the Cloudflare dashboard** (Zero Trust → Networks →
Tunnels):

1. Create a tunnel (Cloudflared connector). Copy its **token** — save it
   to a local file, don't paste it anywhere it'd get logged or committed.
2. Add a **Public Hostname**: your subdomain, Service Type `HTTP`, URL
   `app:8000` (the docker-compose service name — `cloudflared` joins the
   same network as `app`/`db`).
3. Zero Trust → Access → Applications → **Add an application** →
   **Self-hosted** → your domain → add a policy allowing only your own
   email (or a specific Google/GitHub account).

**If the login page shows no login option at all**: email-code login
(One-Time PIN) isn't necessarily on by default — search the Zero Trust
dashboard for "login methods" (its exact location has moved around
Cloudflare's own UI more than once; the dashboard's own search is more
reliable than any menu path written down here) and add **One-Time
PIN** — no external OAuth app needed, just adding it to the account's
enabled login methods. Confirm it's also selected on the Application
itself if there's a per-application login-methods field, not just
enabled account-wide.

**Wiring it to the VM:**

- Fresh VM: `setup.sh` prompts for the token (paste it, or leave blank to
  skip this entirely) and passes it as instance metadata alongside the
  deploy key.
- Existing VM: add it after the fact —
  ```bash
  gcloud compute instances add-metadata postwarden-vm \
    --zone=us-central1-a --project=your-project-id \
    --metadata-from-file=cloudflare-tunnel-token=/path/to/token-file
  gcloud compute ssh postwarden-vm --zone=us-central1-a --project=your-project-id \
    --tunnel-through-iap -- 'sudo google_metadata_script_runner startup'
  ```
  (re-runs `startup-script.sh`, which now finds the token, writes it into
  `/opt/postwarden/.env` alongside `COMPOSE_PROFILES=cloudflared`, and starts
  the `cloudflared` service — nothing else about the deployment changes.)

`docker-compose.yml`'s `cloudflared` service is behind a compose
**profile**, so it's entirely inert for local dev — a plain
`docker compose up` never starts it, on your machine or the VM, unless
`COMPOSE_PROFILES=cloudflared` is set.

## 4. Backups (optional, recommended — it's real financial data)

The database lives in a Docker named volume on the VM's boot disk. That
survives reboots and redeploys, but not a deleted/recreated VM. To back up
to Cloud Storage:

```bash
gsutil mb -l us-central1 gs://your-postwarden-backups   # once
gcloud compute scp backup.sh postwarden-vm:/opt/postwarden/backup.sh \
  --zone=us-central1-a --project=your-project-id --tunnel-through-iap
```

Then, on the VM (`gcloud compute ssh postwarden-vm --tunnel-through-iap`),
install the Cloud SDK if it isn't already there and schedule
`backup.sh` daily, e.g. as a cron entry:

```
0 6 * * * POSTWARDEN_BACKUP_BUCKET=gs://your-postwarden-backups /opt/postwarden/backup.sh
```

To restore: `gsutil cp gs://your-postwarden-backups/postwarden-<stamp>.sql.gz - | gunzip | docker compose exec -T db psql -U postwarden -d postwarden`.

## Cost

`e2-micro` + a 20GB standard persistent disk is within GCP's [always-free
tier](https://cloud.google.com/free/docs/free-cloud-features#compute) in
`us-west1`/`us-central1`/`us-east1` — realistically **$0/month** for a
personal, low-traffic ledger, plus pennies for any Cloud Storage backups.
IAP tunneling itself is free. If Postgres+app feel memory-constrained on
1GB RAM, `--machine-type=e2-small` is the next step up (no longer free,
~$12/month).

## demo.postwarden.org and beta.postwarden.org

Not this VM, and not this repo. The two public instances run on a second,
dedicated VM (`postwarden-public`) that PostWardenLabs operates, and
everything about running *those* specifically — the shared Cloudflare
Tunnel, beta's CI deploy, demo's nightly reset — lives in
[PostWardenPublic](https://github.com/PostWardenLabs/PostWardenPublic), a
separate repo. Nothing here depends on it, and self-hosting your own
instance never requires looking at it — it's PostWardenLabs' own
operational setup, documented in the open the same way this file is, not
a second thing you need to understand to run PostWarden yourself.

## Tearing it down

```bash
gcloud compute instances delete postwarden-vm --zone=us-central1-a --project=your-project-id
gcloud compute firewall-rules delete postwarden-vpc-allow-iap-ssh postwarden-vpc-allow-iap-app --project=your-project-id
gcloud compute networks delete postwarden-vpc --project=your-project-id
```

This deletes the boot disk (and the database with it) unless you took a
backup first — see step 4. `postwarden-public` (demo/beta) is a
separate instance in the same VPC — `gcloud compute instances delete
postwarden-public ...` on its own; leave the VPC/firewall rules alone
if your personal instance is still using them.

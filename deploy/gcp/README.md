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
3. Creates a **dedicated VPC** (`libro-vpc`) — a network you create yourself
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

## Public domain via Cloudflare Tunnel (optional)

If you'd rather visit `https://libro.yourdomain.com` than run a `gcloud`
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
  gcloud compute instances add-metadata libro-vm \
    --zone=us-central1-a --project=your-project-id \
    --metadata-from-file=cloudflare-tunnel-token=/path/to/token-file
  gcloud compute ssh libro-vm --zone=us-central1-a --project=your-project-id \
    --tunnel-through-iap -- 'sudo google_metadata_script_runner startup'
  ```
  (re-runs `startup-script.sh`, which now finds the token, writes it into
  `/opt/libro/.env` alongside `COMPOSE_PROFILES=cloudflared`, and starts
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

## demo.postwarden.org and beta.postwarden.org

The two public instances aren't this VM — they're a second, dedicated
`e2-small` VM (`postwarden-public`, same project and VPC), sized up from
`e2-micro` because it runs *two* full stacks at once and 1GB isn't
comfortable headroom for that. Deliberately a separate machine from
whatever you're using as your own personal instance: a public demo is
the one thing on this project that gets abused or hammered, and it
shouldn't be able to take anything you actually rely on down with it.

Two independent checkouts, `/opt/postwarden-demo` and
`/opt/postwarden-beta`, each just this same `docker-compose.yml`
unmodified — `.env` in each sets `APP_PORT`/`DB_PORT` so they don't
collide on one host (demo: 8000/5432, beta: 8001/5433).

This VM has **its own Cloudflare Tunnel**, separate from whatever
tunnel fronts your personal instance — a new one, created the same way
as "Public domain via Cloudflare Tunnel" above, with two Public
Hostnames (`demo.postwarden.org` → `http://localhost:8000`,
`beta.postwarden.org` → `http://localhost:8001`) instead of one. Its
`cloudflared` connector is **not** the docker-compose-managed profile
service either of the two app stacks ship with — a container in either
compose project's own network can't reach the other's `localhost`
ports, and rather than fight that, `cloudflared` runs standalone,
outside both stacks entirely, with `--network host` so it can just hit
`localhost:8000`/`:8001` directly (both already published there by
`APP_PORT`/`DB_PORT` above):

```bash
sudo docker run -d --name cloudflared --network host --restart unless-stopped \
  cloudflare/cloudflared:latest tunnel run --token <paste the new tunnel's token>
```

demo is world-readable; beta sits behind a Cloudflare Access policy
(same mechanism as "Public domain via Cloudflare Tunnel" above)
restricted to specific emails.

- **beta** tracks `master` exactly. `.github/workflows/deploy-beta.yml`
  redeploys it on every push, authenticated via Workload Identity
  Federation rather than a downloaded service-account key (this
  project's org policy disables key creation — WIF is the
  no-long-lived-secret alternative, not a workaround). Data persists
  between deploys; nothing here ever resets it. To reproduce the WIF
  setup for your own fork (one-time, from your own machine):
  ```bash
  gcloud iam service-accounts create postwarden-ci-deploy --project "$PROJECT_ID"
  for ROLE in roles/iap.tunnelResourceAccessor roles/compute.osAdminLogin roles/compute.viewer; do
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:postwarden-ci-deploy@$PROJECT_ID.iam.gserviceaccount.com" \
      --role="$ROLE" --condition=None
  done
  gcloud iam workload-identity-pools create postwarden-github --project "$PROJECT_ID" --location global
  gcloud iam workload-identity-pools providers create-oidc postwarden-beta-deploy \
    --project "$PROJECT_ID" --location global --workload-identity-pool postwarden-github \
    --attribute-mapping "google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
    --attribute-condition "assertion.repository=='<your-org>/<your-repo>'" \
    --issuer-uri "https://token.actions.githubusercontent.com"
  # Then bind roles/iam.workloadIdentityUser on the service account to the
  # resulting principalSet://.../attribute.repository/<your-org>/<your-repo> —
  # see `gcloud iam service-accounts add-iam-policy-binding --help`.
  ```
  Also enable OS Login on the VM (`gcloud compute instances add-metadata
  postwarden-public --metadata enable-oslogin=TRUE`) — without it,
  `gcloud compute ssh` needs metadata *write* access to push an ephemeral
  key, which is broader than the three roles above grant on purpose.
  And in the workflow itself, `mkdir -p ~/.ssh` has to run before the
  `gcloud compute ssh` step — a fresh Actions runner has no `~/.ssh` at
  all, and `gcloud compute ssh` can't create that directory *and*
  generate its managed keypair in one non-interactive shot; without it,
  the failure is exactly "The private SSH key file for gcloud does not
  exist," which reads like a missing-credential problem but isn't one.
- **demo** deploys from the latest git *tag*, not master — a deliberate
  "this commit is stable enough to show a stranger" decision, cut with
  `git tag vX.Y.Z && git push --tags` and rolled out by hand with
  `deploy-demo.sh` (not on every push; see the script for why).
  Independent of that, `reset-demo.sh` runs nightly via cron **on the
  VM itself** and wipes demo back to seed data — a public, anonymous
  instance needs a reset regardless of how often the code under it
  changes. `LIBRO_ADMIN_USER`/`LIBRO_ADMIN_PASSWORD` **must** be set in
  demo's `.env` (see `reset-demo.sh`'s own comment) or a reset locks
  everyone out, not just visitors.

**Org policies you may hit provisioning any of this from scratch**,
both encountered setting this up and both sensible defaults, not bugs:
*deploy keys* can be disabled org-wide (Organization settings →
security) — if so, either re-enable them or, better, just make the repo
public and clone over plain HTTPS instead, which is what this project
ended up doing; *service-account key creation* can be blocked by an org
policy (`constraints/iam.disableServiceAccountKeyCreation`) — that's
what pushed `deploy-beta.yml` toward Workload Identity Federation
instead of a downloaded key, which is the better practice anyway.

## Tearing it down

```bash
gcloud compute instances delete libro-vm --zone=us-central1-a --project=your-project-id
gcloud compute firewall-rules delete libro-vpc-allow-iap-ssh libro-vpc-allow-iap-app --project=your-project-id
gcloud compute networks delete libro-vpc --project=your-project-id
```

This deletes the boot disk (and the database with it) unless you took a
backup first — see step 4. `postwarden-public` (demo/beta) is a
separate instance in the same VPC — `gcloud compute instances delete
postwarden-public ...` on its own; leave the VPC/firewall rules alone
if your personal instance is still using them.

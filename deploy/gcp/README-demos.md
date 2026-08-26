# PostWardenPublic — running demo.postwarden.org and beta.postwarden.org

This is PostWardenLabs' own operational setup for the two *public* instances
of PostWarden — it is not something a self-hoster needs, and self-hosting
PostWarden never requires GCP, Cloudflare, or anything in this repo at all.
If you're setting up your own instance, start with
[PostWarden](https://github.com/PostWardenLabs/PostWarden)'s own README and
(if you want a fully worked GCP example) its `deploy/gcp/README.md` — this
repo assumes you've already read that as the base case (IAP tunneling, the
general Cloudflare Tunnel setup, `setup.sh`'s deploy-key flow) and only
documents what's different for running the two shared public instances.

## The shared VM

`demo.postwarden.org` and `beta.postwarden.org` aren't the personal-instance
VM the main README describes — they're a second, dedicated `e2-small` VM
(`postwarden-public`, same project and VPC as a personal instance would use),
sized up from `e2-micro` because it runs *two* full stacks at once and 1GB
isn't comfortable headroom for that. Deliberately a separate machine from
any personal instance: a public demo is the one thing on this project that
gets abused or hammered, and it shouldn't be able to take anything a real
user relies on down with it.

Two independent checkouts, `/opt/postwarden-demo` and `/opt/postwarden-beta`,
each just PostWarden's own `docker-compose.yml` unmodified — `.env` in each
sets `APP_PORT`/`DB_PORT` so they don't collide on one host (demo: 8000/5432,
beta: 8001/5433).

This VM has **its own Cloudflare Tunnel**, separate from whatever tunnel
fronts a personal instance — a new one, created the same way as "Public
domain via Cloudflare Tunnel" in the main repo's `deploy/gcp/README.md`, with
two Public Hostnames (`demo.postwarden.org` → `http://localhost:8000`,
`beta.postwarden.org` → `http://localhost:8001`) instead of one. Its
`cloudflared` connector is **not** the docker-compose-managed profile service
either app stack ships with — a container in either compose project's own
network can't reach the other's `localhost` ports, and rather than fight
that, `cloudflared` runs standalone, outside both stacks entirely, with
`--network host` so it can just hit `localhost:8000`/`:8001` directly (both
already published there by `APP_PORT`/`DB_PORT` above):

```bash
sudo docker run -d --name cloudflared --network host --restart unless-stopped \
  cloudflare/cloudflared:latest tunnel run --token <paste the new tunnel's token>
```

demo is world-readable; beta sits behind a Cloudflare Access policy (same
mechanism as "Public domain via Cloudflare Tunnel") restricted to specific
emails.

## beta.postwarden.org

beta tracks `master` exactly, authenticated via Workload Identity Federation
rather than a downloaded service-account key (this project's org policy
disables key creation — WIF is the no-long-lived-secret alternative, not a
workaround). Data persists between deploys; nothing here ever resets it.

**Triggering a deploy** — this is the one thing that changed shape by moving
the workflow out of the product repo: `.github/workflows/deploy-beta.yml`
here can only react to events in *this* repo, not a push to PostWarden's
`master`. Right now it's `workflow_dispatch` only — trigger it by hand from
this repo's Actions tab (or run `deploy-beta.sh` directly) after a product
push you want live. The same-day "if it breaks, beta breaks with it"
auto-redeploy property this project had while the workflow lived in the
product repo is **not** currently reproduced — the natural fix is a small
notify-only step added to PostWarden's own CI that fires a
`repository_dispatch` at this repo on every push to `master` (needs a PAT
with repo-dispatch scope, stored as a secret in the product repo, pointing
here — genuine one-time GitHub configuration, not something either repo's
code can set up on its own). Worth doing once this split settles, not done
yet.

To reproduce the WIF setup for your own fork (one-time, from your own
machine):

```bash
gcloud iam service-accounts create postwarden-ci-deploy --project "$PROJECT_ID"
for ROLE in roles/iap.tunnelResourceAccessor roles/compute.instanceAdmin.v1; do
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

**Do not enable OS Login on this VM** (leave `enable-oslogin` unset, or
explicitly `FALSE`) — this was tried first, with `roles/compute.osAdminLogin`
scoped tighter than `instanceAdmin.v1`, and it doesn't work for a *service
account* identity on a project that belongs to a Cloud Identity/Workspace
organization (which most real GCP accounts do): `google_authorized_keys` on
the VM rejects it with "OS Login user ... does not have login permission —
Could not grant access to organization user," regardless of IAM role,
seemingly an org-policy interaction with service-account OS Login
specifically that a plain project-level role grant can't satisfy.
`roles/compute.instanceAdmin.v1` (broader than the OS Login roles, but the
one that actually works) falls back to the older metadata-based flow
instead: `gcloud compute ssh` pushes an ephemeral key straight into the
instance's metadata, which needs `compute.instances.setMetadata` — this is
the same mechanism manual access already uses via `setup.sh`'s deploy key,
just done automatically per-run instead of once.

That flow needs one more grant `instanceAdmin.v1` alone doesn't cover:
`roles/iam.serviceAccountUser` on **the VM's own attached service account**
(its default Compute Engine SA, `<project-number>-compute@
developer.gserviceaccount.com` — `gcloud iam service-accounts list` to find
yours), not on `postwarden-ci-deploy` itself:

```bash
gcloud iam service-accounts add-iam-policy-binding \
  <project-number>-compute@developer.gserviceaccount.com \
  --member="serviceAccount:postwarden-ci-deploy@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"
```

Without it: "The user does not have access to service account
'...-compute@developer.gserviceaccount.com'... Ask a project owner to grant
you the iam.serviceAccountUser role on the service account" — GCP's own
metadata-write path treats attaching an SSH key to a VM as partially "acting
as" whatever service account that VM runs as, so the caller needs standing
on *that* identity too, not just permission on the instance.

Also, in the workflow itself, `mkdir -p ~/.ssh` has to run before the
`gcloud compute ssh` step — a fresh Actions runner has no `~/.ssh` at all,
and `gcloud compute ssh` can't create that directory *and* generate its
managed keypair in one non-interactive shot; without it, the failure is
exactly "The private SSH key file for gcloud does not exist," which reads
like a missing-credential problem but isn't one.

`deploy-beta.sh` and the workflow both ping the VM in a short retry loop
before the real (docker-build-including, much more expensive to fail)
deploy command — cheap insurance against gcloud's own documented "SSH key
not propagated yet, try again" case for a brand-new identity. It was *not*,
in the end, what actually caused this to fail repeatedly while setting it
up, though — that turned out to be a real bug, found by checking the VM
directly rather than trusting a plausible-sounding gcloud error message a
second time: `/home/runner`'s home directory (and its default dotfiles)
ended up owned by a stale, no-longer-existent UID/GID from an earlier
half-finished provisioning attempt, while `.ssh/authorized_keys` itself —
created fresh — had the *correct* current ownership. sshd's `StrictModes`
(on by default) silently refuses to use an `authorized_keys` file if *any*
ancestor directory has the wrong owner, so the key being present and
correctly formatted didn't matter. Fixed with
`sudo chown -R runner:runner /home/runner`; if `deploy-beta.sh` or the
workflow ever fails again with "Permission denied (publickey)" that the
retry loop doesn't resolve, check ownership on the VM before assuming it's a
propagation delay again — `sudo stat -c "%U:%G %n" /home/runner
/home/runner/.ssh /home/runner/.ssh/authorized_keys` should show the same
owner on all three.

## demo.postwarden.org

demo deploys from the latest git *tag*, not master — a deliberate "this
commit is stable enough to show a stranger" decision, cut with
`git tag vX.Y.Z && git push --tags` in the product repo and rolled out by
hand with `deploy-demo.sh` (not on every push; see the script for why).
Independent of that, `reset-demo.sh` runs nightly via cron **on the VM
itself** and wipes demo back to seed data — a public, anonymous instance
needs a reset regardless of how often the code under it changes.
`POSTWARDEN_ADMIN_USER`/`POSTWARDEN_ADMIN_PASSWORD` **must** be set in
demo's `.env` (see `reset-demo.sh`'s own comment) or a reset locks everyone
out, not just visitors. `POSTWARDEN_DEMO_MODE=true` should be set there too
— it's what puts the credentials banner on `login.html` in the first place
(see the product repo's `app/main.py` `demo_banner` comment and
`docs/ARCHITECTURE.md`'s Auth route entry); a fresh install without it is a
perfectly normal self-hosted instance with no banner at all, and since
`reset-demo.sh` re-creates the container from a fresh volume every night, an
`.env` missing this flag means the banner silently disappears at the next
reset even though the login itself still works fine with the same
credentials.

## Org policies you may hit provisioning any of this from scratch

Both encountered setting this up and both sensible defaults, not bugs:
*deploy keys* can be disabled org-wide (Organization settings → security) —
if so, either re-enable them or, better, just make the product repo public
and clone over plain HTTPS instead, which is what this project ended up
doing; *service-account key creation* can be blocked by an org policy
(`constraints/iam.disableServiceAccountKeyCreation`) — that's what pushed
`deploy-beta.yml` toward Workload Identity Federation instead of a
downloaded key, which is the better practice anyway.

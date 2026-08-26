# Working in this repo

PostWarden is a personal general ledger — PostgreSQL enforces the accounting
(double-entry balance, immutability, hierarchy integrity) at the schema
level via triggers; FastAPI + Jinja2 + vanilla JS is a thin layer on top.
No ORM, no build step, no SPA. Before touching anything, read:

- [`README.md`](README.md) — what the app is, how to run it
- [`SPEC.md`](SPEC.md) — *why* the schema is shaped this way; read this
  before modeling anything new, especially anything touching scenarios,
  balance enforcement, or the ledger/budget split
- [`docs/SCHEMA.md`](docs/SCHEMA.md) — the ER diagram and table reference
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the app code and
  UI patterns are organized

## The standing rule: documentation ships with the feature, not after it

**Every feature, schema change, or meaningful behavior change updates
the relevant doc(s) in the same piece of work — before calling the task
done, not as a follow-up someone has to remember to ask for.** A design
decision that isn't in `SPEC.md` and a table that isn't in
`docs/SCHEMA.md` didn't happen, as far as the next session (or the next
person) reading this repo is concerned. Concretely, whenever a change:

- **adds or changes a table, column, trigger, view, or function** →
  update `docs/SCHEMA.md` (the table reference, and the ER diagram if
  it adds a relationship or a table worth showing) and, if there's a
  *reason* behind the shape (not just "the app needed a column") →
  add or revise a numbered decision in `SPEC.md`.
- **adds a route, a new screen, or a new reusable JS/CSS pattern** →
  update `docs/ARCHITECTURE.md`'s route table or pattern list.
- **changes what a user-facing feature does** → update `README.md`'s
  "What you get" list if it's the kind of thing a newcomer skimming the
  README would want to know exists.
- **is a pure UI/CSS polish pass with no behavioral or structural
  change** (an icon nudge, a color tweak) → does *not* need a doc
  update. Use judgment: the bar is "would the architecture/schema docs
  now be wrong or incomplete," not "did any file change."

If a change is large enough to need a design conversation before writing
code (the kind of thing this project's own history shows happening —
see `git log`, e.g. the scenario/budget redesign), treat the resulting
`SPEC.md` decision as part of the deliverable, not optional
documentation debt. Write it in the same voice as what's already there:
explain the rejected alternative, not just the chosen one.

Before ending a work session that touched the schema or app structure,
scan the diff and ask: *does `docs/SCHEMA.md` or `docs/ARCHITECTURE.md`
still accurately describe what's now in the repo?* If not, fix it before
considering the task finished.

## Working conventions established in this repo

- **Local testing before deploy, every time.** `docker compose up -d
  --build`; if `db/schema.sql` changed, `docker compose down -v` first
  (init scripts only run on a fresh volume) — see `docs/ARCHITECTURE.md`
  and the README's "Tests" section for the exact pytest invocation
  (`POSTWARDEN_TEST_ADMIN_URL`/`POSTWARDEN_TEST_URL` pointed at `127.0.0.1:5432`
  when running pytest from the host against the Dockerized Postgres).
- **Manual browser verification for anything visual or interactive** —
  the Playwright-driven browser tools in this environment, not just
  pytest — before considering a UI change done, especially anything
  involving hover states, live client-side recompute, or drag/collapse
  interaction.
- **Deploys.** There is currently no maintainer personal instance —
  `libro-vm` (the dev-era VM the project lived on before it had a real
  deploy story) has been decommissioned. `deploy/gcp/` in *this* repo is
  now a generic, fully-worked example of running PostWarden on GCP —
  useful to anyone who wants that specific setup, not a description of
  infrastructure that's actually running. `demo.postwarden.org` and
  `beta.postwarden.org` are real and running, but everything about
  deploying *them* specifically — `deploy-beta.sh`/`deploy-beta.yml`
  (beta, auto-redeployed on every push here via
  `.github/workflows/notify-postwarden-public.yml`'s `repository_dispatch`
  — see that workflow's own comments for the PAT it depends on),
  `deploy-demo.sh`/`reset-demo.sh` (demo, tag-based + nightly reset) —
  lives in a separate repo,
  [PostWardenPublic](https://github.com/PostWardenLabs/PostWardenPublic),
  not here. If a task involves changing how beta/demo actually deploy,
  that's a change in that repo, not this one. This repo's own
  `notify-postwarden-public.yml` is the one piece of that story that
  *does* live here — touch it if the dispatch event name/shape ever
  needs to change on this side.
- **Numbered migrations are on the shelf for now — do not add files
  to `db/migrations/`.** The mechanism (`app/migrate.py`,
  `schema_version`, `db/migrations/README.md`'s own instructions)
  stays in the repo and stays correct, because it's real
  infrastructure worth having once it's needed — it's just unused at
  the moment. Every instance that exists right now (`beta.postwarden.org`,
  `demo.postwarden.org`) holds only dummy/test data, confirmed by the
  user, and nobody outside this project depends on any of it surviving
  a redeploy. That makes a migration's entire reason to exist —
  applying a schema change to an existing database *without* losing
  what's in it — a cost with no matching benefit right now, so schema
  changes ship the simple way everywhere: fold the change into
  `db/schema.sql` directly, `git pull`, `docker compose down -v` (a
  `pg_dump` backup first if you'd rather not retype anything),
  `docker compose up -d --build`. This is a deliberate, revisitable
  choice, not a permanent one — the moment any instance holds data
  worth preserving across a schema change (a real maintainer instance,
  most likely first), switch back: resume adding
  `db/migrations/NNN_*.sql` files per that directory's own README, and
  update this bullet to say so.
  Verify after every deploy: check `docker compose logs app` for
  startup errors, hit a few unauthenticated routes to confirm `303`
  (not `500`), and directly exercise any new SQL function/trigger
  against real data via `psql` before calling it done.
- **`docs.postwarden.org`** builds from `docs/` via `mkdocs.yml`
  (Cloudflare Pages, redeploys on push — no separate workflow needed).
  `docs/SPEC.md` is a **symlink** to the real `../SPEC.md`, not a copy —
  never replace it with an actual file, that's exactly the doc-drift
  this whole convention exists to prevent.
- **Commit messages** in this repo explain the *why*, at some length —
  see `git log` for the standard to match. They're also this project's
  de facto changelog; `SPEC.md`'s "Extension roadmap" section has
  started citing them directly (struck-through items note what actually
  shipped and how it differed from the original proposal).
- **`VERSION`** (repo root, plain text, shown in the footer) bumps with
  any user-visible change — patch for a fix/polish pass, minor for a new
  feature, same pre-1.0 rules either way since this is still v0.x. Bump
  it in the same commit as the change, not a separate one.

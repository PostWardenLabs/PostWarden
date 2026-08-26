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
  (`LIBRO_TEST_ADMIN_URL`/`LIBRO_TEST_URL` pointed at `127.0.0.1:5432`
  when running pytest from the host against the Dockerized Postgres).
- **Manual browser verification for anything visual or interactive** —
  the Playwright-driven browser tools in this environment, not just
  pytest — before considering a UI change done, especially anything
  involving hover states, live client-side recompute, or drag/collapse
  interaction.
- **Deploys — three targets, three cadences**, all documented in
  `deploy/gcp/README.md`, not just this bullet:
  - The maintainer's own instance: `deploy/gcp/redeploy.sh`, run by
    hand, pulls and rebuilds `master`.
  - `beta.postwarden.org`: `deploy/gcp/deploy-beta.sh`, run
    automatically by `.github/workflows/deploy-beta.yml` on every push
    to `master` — if a change breaks something, beta breaks with it,
    same day. Auth is Workload Identity Federation (no service-account
    key — this GCP org disables key creation).
  - `demo.postwarden.org`: deliberately *not* wired to every push.
    `deploy/gcp/deploy-demo.sh` deploys the latest git **tag**, by hand,
    only when a commit is judged demo-worthy (`git tag vX.Y.Z && git
    push --tags` first). `reset-demo.sh` runs nightly via cron **on
    that VM**, independent of deploys, wiping demo back to seed data —
    it's the one public, anonymous, unauthenticated instance.
  - Any schema change gets a `pg_dump` backup on the relevant VM
    *first*, applied either via a plain re-init (`docker compose down
    -v` — acceptable for the maintainer's own instance, which holds
    only dummy/test data, confirmed by the user; demo gets this
    automatically every night anyway) or, for an existing database
    that has to keep its data (beta, and eventually the maintainer's
    own real instance), by adding a numbered file to
    `db/migrations/` — see that directory's `README.md` and
    `app/migrate.py`'s docstring. `app/migrate.py` runs automatically
    from FastAPI's `lifespan` on every startup and applies whatever's
    pending, in order, each in its own transaction, so a normal
    `git pull && docker compose up -d --build` (see the README's
    "Updating" section) is enough for beta and any future
    keep-the-data deploy — no separate migration step to remember, no
    manual `psql` unless a change is unusually large or risky and
    you want to watch it run. The migration file *also* gets folded
    into `db/schema.sql` directly (with `schema_version`'s seed
    bumped to match) so a fresh install still gets the full current
    state in one shot rather than replaying history — the two have to
    move together, `db/migrations/README.md` says so too.
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

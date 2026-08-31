# Working in this repo

PostWarden is a personal general ledger. PostgreSQL enforces the
accounting (double-entry balance, immutability, hierarchy integrity) at
the schema level via triggers — the application layer never has to, and
a bug in that layer cannot corrupt the ledger, only misreport it. The
app on top is a FastAPI backend (vertical-slice modules, a pure domain
layer, SQLAlchemy Core, Alembic) serving a JSON API to a React +
TypeScript SPA.

Read, in this order:

- [`README.md`](README.md) — what the app is, how to run it
- [`docs/GUIDE.md`](docs/GUIDE.md) — the user-facing concepts guide:
  what PostWarden is/isn't, why double-entry for personal finance,
  chart-of-accounts patterns. Not code-relevant day to day, but keep it
  in sync if a change touches what `db/seed.sql` ships or how
  scenarios/budgets are explained to a newcomer.
- [`SPEC.md`](SPEC.md) — *why* the schema is shaped this way
- [`docs/SCHEMA.md`](docs/SCHEMA.md) — the ER diagram and table reference
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the app code and
  UI patterns are organized: the backend's vertical slices, the
  frontend's five component archetypes, the reasoning behind both
- [`ROADMAP.md`](ROADMAP.md) — the master plan: vision, the sequenced
  tracks, the decision register. **The only file in this repo that
  contains plans** — a design exploration may grow notes anywhere, but
  ordering opinions live there or they don't exist

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
- **changes what a user-facing feature does** → update `README.md`'s
  "What you get" list if it's the kind of thing a newcomer skimming the
  README would want to know exists.
- **changes the backend or frontend structure** — a new module, a new
  widget, a new component archetype → update `docs/ARCHITECTURE.md`.
- **is a pure UI/CSS polish pass with no behavioral or structural
  change** (an icon nudge, a color tweak) → does *not* need a doc
  update. Use judgment: the bar is "would the architecture/schema docs
  now be wrong or incomplete," not "did any file change."

Before ending a work session that touched the schema or app structure,
scan the diff and ask: *does `docs/SCHEMA.md` or `docs/ARCHITECTURE.md`
still accurately describe what's now in the repo?* If not, fix it before
considering the task finished.

## Working conventions

- **One instance, deterministic seed.** The local instance loads
  `schema.sql` + `seed.sql` + `seed_demo.sql`. `seed_demo.sql` is
  **mandatory**, not optional: `seed.sql` alone seeds accounts,
  scenarios and levels with no journal entries at all, and an empty
  ledger cannot verify a report. Entry ids are random 6-character codes
  (`SPEC.md` decision 17), so compare on `(date, description, amount)`,
  never on id.
- **Local testing before calling anything done.** `docker compose up -d
  --build`; if `db/schema.sql` changed, `docker compose down -v` first
  (init scripts only run on a fresh volume). See the README's "Tests"
  section for the pytest invocation
  (`POSTWARDEN_TEST_ADMIN_URL`/`POSTWARDEN_TEST_URL` pointed at
  `127.0.0.1:5432` when running pytest from the host against the
  Dockerized Postgres).
- **The 60 pure-Postgres tests are the safety net and stay green,
  unchanged, at every point.** `tests/test_invariants.py` and
  `tests/test_cashflow.py` never import the app, so they're valid
  regardless of what the application layer looks like. If a change
  requires editing one of them, that's a signal something's wrong with
  the change, not with the test.
- **Tests ship with the module they cover.** A new route, service
  function, or domain function gets its `apitests/` coverage in the
  same piece of work — `router.py`/`service.py`/`repository.py` each
  get their own `test_*.py` under the matching `apitests/modules/<name>/`
  directory; `domain/` functions get theirs under `apitests/domain/`,
  with no database fixtures at all (that's the point of the domain
  layer being pure).
- **CI runs `pytest` against Postgres service containers** — two
  separate jobs, one for `tests/` (raw-SQL schema) and one for
  `apitests/` (Alembic-provisioned schema); see
  `.github/workflows/backend-ci.yml`'s own comments for why they're kept
  apart, and `apitests/conftest.py` for why `apitests/` is a top-level
  directory rather than nested under `tests/`.
- **Manual browser verification for anything visual or interactive** —
  the browser tools in this environment, not just pytest — before
  considering a UI change done. Especially hover states, live
  client-side recompute, focus management, and collapse/drag
  interaction. The widgets in `frontend/src/widgets/` encode real
  browser-quirk fixes (`e.code` not `e.key` for Option shortcuts,
  explicit `tabIndex` for Safari's tab order, the iOS `select()` no-op),
  and an off-the-shelf replacement will not reproduce them by default.
- **Plan a screen against its whole archetype, not just the one page
  that prompted it.** `docs/ARCHITECTURE.md`'s "Component archetypes" +
  "Archetype conventions" sections group every page into a small set of
  shapes because pages doing the same job kept drifting apart. If you
  find yourself writing a second bespoke report page, stop — the
  archetype component is the deliverable.
- **Migrations use Alembic.** `db/schema.sql` remains the source of
  truth for a fresh install; Alembic's baseline revision is that same
  schema, and every change forward from there is a real migration under
  `alembic/versions/`.
- **Deploys.** `demo.postwarden.org` and `beta.postwarden.org` both
  follow `master` directly. Everything about deploying them —
  `deploy-beta.sh`/`deploy-beta.yml`, `deploy-demo.sh`/`reset-demo.sh` —
  lives in
  [PostWardenPublic](https://github.com/PostWardenLabs/PostWardenPublic),
  not here. `deploy/gcp/` in *this* repo is a generic worked example of
  running PostWarden on GCP, not a description of live infrastructure.
  This repo's own `notify-postwarden-public.yml` is the one piece of the
  deploy story that does live here.
  **Verify every deploy authenticated**, not just with an unauthenticated
  route sweep: `auth_gate`-equivalent per-route auth redirects/401s
  before any route body — and therefore any query — ever runs, so an
  unauthenticated `303`/`404` check only proves the process is up, not
  that a given handler's queries actually succeed. Log in for real, then
  check `200` on the routes that touch data.
- **`docs.postwarden.org`** builds from `docs/` via `mkdocs.yml`
  (Cloudflare Pages, redeploys on push to `master` — no separate
  workflow). `docs/SPEC.md` is a **symlink** to the real `../SPEC.md`,
  not a copy — never replace it with an actual file, that's exactly the
  doc-drift this whole convention exists to prevent. `ROADMAP.md` is
  deliberately *not* in the mkdocs nav: internal planning, not
  published reference.
- **One commit per unit of work, worked sequentially.** Implement one
  thing, verify it, commit it, then move to the next — do not build
  several and squash them at the end. The test is whether a commit
  could be reverted on its own without taking an unrelated change down
  with it. Bundle only what is incoherent apart (a module and its own
  tests; a rename and every call site).
- **Commit messages explain the *why*, at some length** — see `git log`
  for the standard to match. They are also this project's de facto
  changelog.
- **`VERSION`** tracks user-visible change; bump it whenever a change is
  user-visible. Local dev note: the hot-reload override
  (`docker-compose.override.yml`) only bind-mounts `./src`, so a bumped
  `VERSION` won't appear in the running container's footer until a real
  `docker compose -f docker-compose.yml up -d --build`.

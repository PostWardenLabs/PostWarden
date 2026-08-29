# Working in this repo — on the `rebuild` branch

PostWarden is a personal general ledger — PostgreSQL enforces the
accounting (double-entry balance, immutability, hierarchy integrity) at
the schema level via triggers. **That half is not changing.** The
application layer on top of it is being rebuilt on this branch:
FastAPI + Jinja2 + vanilla JS is being replaced by a restructured
FastAPI backend (vertical-slice modules, a pure domain layer,
SQLAlchemy Core, Alembic) and a React + TypeScript SPA.

**Read [`REBUILD.md`](REBUILD.md) first.** It carries the context, the
numbered decisions and their rejected alternatives, the phase roadmap,
and — in §9 — what would make us stop. Everything below assumes it.

Then, as before:

- [`README.md`](README.md) — what the app is, how to run it
- [`docs/GUIDE.md`](docs/GUIDE.md) — the user-facing concepts guide:
  what PostWarden is/isn't, why double-entry for personal finance,
  chart-of-accounts patterns. Not code-relevant day to day, but keep it
  in sync if a change touches what `db/seed.sql` ships or how
  scenarios/budgets are explained to a newcomer.
- [`SPEC.md`](SPEC.md) — *why* the schema is shaped this way. Still
  fully in force: the schema is the one thing this rebuild does not
  touch, so every decision in here still binds.
- [`docs/SCHEMA.md`](docs/SCHEMA.md) — the ER diagram and table reference
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how the *current*
  app code and UI patterns are organized. On this branch it is a
  **source document, not a description of the tree**: it is the most
  complete account of what the old app does, section by section, and
  porting work should be read out of it. It gets rewritten at cutover,
  not before.
- [`UI_CONSISTENCY_AUDIT.md`](UI_CONSISTENCY_AUDIT.md) — §1's five
  archetypes are now the **component spec for the new frontend**. It was
  written before anyone decided to rebuild and turns out to be exactly
  the right decomposition.

## Branch discipline

- **`master` stays working and stays untouched.** It is a git-level
  fallback only, in case this effort is abandoned — not a running
  comparison target; no second live container is maintained for
  diffing against it (`REBUILD.md` §5.6). Do not refactor it, do not
  "quickly fix" things on it while passing through, and do not merge
  `rebuild` into it until the cutover in `REBUILD.md` §8.
- **Pushing `rebuild` does not deploy anything.**
  `.github/workflows/notify-postwarden-public.yml` fires its
  `repository_dispatch` on pushes to `master` *specifically*, so beta
  only ever follows `master`. That is why this work belongs on a branch:
  beta keeps running the shipped app for the whole rebuild instead of
  running a half-finished one for weeks.
- A fix that genuinely belongs to the *current* app (a real bug someone
  hits on beta) goes on `master` and gets merged forward, not written
  twice.

## The standing rule: documentation ships with the feature, not after it

Unchanged, and it applies to rebuild work too — with one addition at the
end.

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
- **is a pure UI/CSS polish pass with no behavioral or structural
  change** (an icon nudge, a color tweak) → does *not* need a doc
  update. Use judgment: the bar is "would the architecture/schema docs
  now be wrong or incomplete," not "did any file change."
- **changes the rebuild's own shape** — a phase reordered, a decision
  reversed, a widget that turned out to need porting rather than
  replacing → update `REBUILD.md`. Same standard as `SPEC.md`: write
  the rejected alternative, not just the chosen one. §5 is numbered for
  exactly this reason.

Note that `docs/ARCHITECTURE.md` is deliberately **not** on that list
while this branch is live — see the reading list above. It describes the
old tree, is being mined for the port, and is rewritten once at cutover.

Before ending a work session that touched the schema or app structure,
scan the diff and ask: *does `docs/SCHEMA.md` or `REBUILD.md` still
accurately describe what's now in the repo?* If not, fix it before
considering the task finished.

## Working conventions

- **One instance, deterministic seed.** This is a committed, all-in
  rebuild, not a parallel-track migration — `master` is a git fallback
  only, no second live container is kept running to diff against (see
  `REBUILD.md` §5.6). The new instance loads `schema.sql` + `seed.sql`
  + `seed_demo.sql`. `seed_demo.sql` is **mandatory**, not optional:
  `seed.sql` alone seeds accounts, scenarios and levels with no journal
  entries at all, and an empty ledger cannot verify a report. Entry ids
  are random 6-character codes (`SPEC.md` decision 17), so compare on
  `(date, description, amount)`, never on id.
- **Local testing before calling anything done.** `docker compose up -d
  --build`; if `db/schema.sql` changed, `docker compose down -v` first
  (init scripts only run on a fresh volume). See the README's "Tests"
  section for the pytest invocation
  (`POSTWARDEN_TEST_ADMIN_URL`/`POSTWARDEN_TEST_URL` pointed at
  `127.0.0.1:5432` when running pytest from the host against the
  Dockerized Postgres).
- **The 60 pure-Postgres tests are the safety net and stay green,
  unchanged, at every point.** `tests/test_invariants.py` and
  `tests/test_cashflow.py` never import the app, so they are valid
  against the new backend exactly as written. If a change requires
  editing one of them, that is a signal something is wrong with the
  change, not with the test.
- **Tests ship with their module, not as a phase.** Port the *intent* of
  the existing suite, not its mechanism — roughly 49 current tests
  regex-scrape rendered HTML (`tests/test_auth.py:1226`) and those
  assertions get shorter, not longer, against a JSON API. `REBUILD.md`
  §5.4 explains why no golden-master capture is being taken, which is
  the non-obvious part.
- **CI runs `pytest` against a Postgres service container**, and lands
  with the first backend module. The repo had none before this branch.
- **Manual browser verification for anything visual or interactive** —
  the browser tools in this environment, not just pytest — before
  considering a UI change done. Especially hover states, live
  client-side recompute, focus management, and collapse/drag
  interaction. This mattered before and matters more now: the widgets
  being replaced encode real browser-quirk fixes (`e.code` not `e.key`
  for Option shortcuts, explicit `tabIndex` for Safari's tab order, the
  iOS `select()` no-op), and an off-the-shelf component will not
  reproduce them by default.
- **Plan a screen against its whole archetype, not just the one page
  that prompted it.** `UI_CONSISTENCY_AUDIT.md` §1 groups every page
  into one of five shapes (Filterable transaction list, Point-in-time
  report, Range/period report, Editable grid, Management/CRUD) because
  pages doing the same job kept drifting apart. On this branch that
  stops being a review convention and becomes the actual build order:
  one component per archetype, then configuration. If you find yourself
  writing a second bespoke report page, stop — the archetype component
  is the deliverable.
- **Migrations are live again — use Alembic.** This reverses `master`'s
  standing "do not add files to `db/migrations/`" rule, and the reasoning
  is in `REBUILD.md` §5.5. The hand-rolled `app/migrate.py` mechanism
  and `db/migrations/` are retired on this branch. `db/schema.sql`
  remains the source of truth for a fresh install; Alembic's baseline
  revision is the current schema.
- **Deploys.** `demo.postwarden.org` and `beta.postwarden.org` both
  follow `master` and are unaffected by this branch (see Branch
  discipline). Everything about deploying them —
  `deploy-beta.sh`/`deploy-beta.yml`, `deploy-demo.sh`/`reset-demo.sh` —
  lives in
  [PostWardenPublic](https://github.com/PostWardenLabs/PostWardenPublic),
  not here. `deploy/gcp/` in *this* repo is a generic worked example of
  running PostWarden on GCP, not a description of live infrastructure.
  This repo's own `notify-postwarden-public.yml` is the one piece of the
  deploy story that does live here.
  At cutover, verify **authenticated**: an unauthenticated `303` sweep
  proves nothing, because `auth_gate` redirects before any route body —
  and therefore any query — ever runs.
- **`docs.postwarden.org`** builds from `docs/` via `mkdocs.yml`
  (Cloudflare Pages, redeploys on push to `master` — no separate
  workflow). `docs/SPEC.md` is a **symlink** to the real `../SPEC.md`,
  not a copy — never replace it with an actual file, that's exactly the
  doc-drift this whole convention exists to prevent. `REBUILD.md` is
  deliberately *not* in the mkdocs nav: it is internal planning, like
  `BACKLOG.md` and `UI_CONSISTENCY_AUDIT.md`, not published reference.
- **One commit per unit of work, worked sequentially.** Implement one
  thing, verify it, commit it, then move to the next — do not build
  several and squash them at the end. The test is whether a commit
  could be reverted on its own without taking an unrelated change down
  with it. Bundle only what is incoherent apart (a module and its own
  tests; a rename and every call site).
- **Commit messages explain the *why*, at some length** — see `git log`
  for the standard to match. They are also this project's de facto
  changelog.
- **`VERSION`** stays where it is for most of this branch. It tracks
  user-visible change, and until cutover there is no user-visible
  change — the shipped app is whatever `master` is serving. Bump it as
  part of the cutover, not per phase. (Local dev note that still
  applies: the hot-reload override only bind-mounts `./app`, so a
  bumped `VERSION` won't appear in the running container's footer until
  a real `docker compose up -d --build`.)

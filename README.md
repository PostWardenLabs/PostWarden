# Libro

A personal general ledger where **the database guarantees the accounting**.

Double-entry, accrual-capable, with OneStream-style **scenarios** (ACTUAL,
budgets, forecasts) as a first-class dimension. PostgreSQL holds the truth;
a small FastAPI app gives you a trial balance, a keyboard-first journal
entry screen, a journal browser, chart-of-accounts management, and scenario
management. Power BI and Excel connect straight to the database through
purpose-built reporting views.

## Why it exists

GnuCash stores in SQL but enforces nothing there — no foreign keys, balance
checked only in C++, key-value `slots` everywhere. Actual Budget has a clean
schema but is single-entry envelope budgeting at heart. Libro takes the
opposite bet: push every accounting invariant into PostgreSQL itself, keep
the application thin, and treat budgets as just another scenario of journal
entries so that *variance is a query, not a module*.

What the database refuses to accept, no matter what client asks:

- an unbalanced entry in a scenario that enforces balance (checked at COMMIT
  by a deferred constraint trigger — the transaction simply fails)
- an entry with no lines
- a line posted to a summary or inactive account
- any edit or delete of a posted line (history is append-only; you reverse)
- an entry in a locked scenario
- a child account whose type differs from its parent, or a hierarchy cycle

## Run it (Docker)

```bash
docker compose up --build
```

Then open http://localhost:8000. The database initializes itself on first
boot (schema + starter chart of accounts + a few demo entries; remove the
`03_seed_demo.sql` line in `docker-compose.yml` for a clean start).

Postgres is exposed on `localhost:5432` (user/db/password: `libro`) so
Power BI, Excel, or psql can connect directly.

## Run it (local, no Docker)

Requires PostgreSQL 14+ and Python 3.11+.

```bash
./scripts/init_db.sh --with-demo     # create + load the database
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Set `DATABASE_URL` if your Postgres isn't `libro:libro@localhost:5432/libro`.

## Security notes

Every screen and `/api/*` route requires a login — see "Creating a login"
below to set one up. A session is an opaque random token stored in
Postgres (`sessions`, checked on every request); logging out or resetting
a password deletes it, no signing secret to manage. State-changing POSTs
(posting an entry, reversing one, locking a scenario, ...) also require a
per-session CSRF token, rendered as a hidden field on every form.

Sessions cookies are `HttpOnly` and `SameSite=Lax` always. They're
`Secure` (HTTPS-only) only if `LIBRO_COOKIE_SECURE=true` is set — that's
**not** the default, because neither of this project's documented
deployment paths terminates HTTPS at uvicorn itself (an IAP tunnel and a
Cloudflare Tunnel both encrypt at the tunnel layer, invisible to the
cookie; a browser still sees plain `http://localhost:8000`). If you put a
reverse proxy in front that terminates real TLS itself, set
`LIBRO_COOKIE_SECURE=true`.

`docker-compose.yml` still binds Postgres to `127.0.0.1` (Power BI/Excel/psql
on the same machine connect fine; the network can't) — change the
`libro`/`libro` database credentials before exposing this beyond a machine
you trust, login or not; the app's login only protects the app, not a
direct Postgres connection.

## Creating a login

No login exists until you create one.

**Docker, easiest:** set `LIBRO_ADMIN_USER` / `LIBRO_ADMIN_PASSWORD` in
`.env` (copy `.env.example`) before the first `docker compose up` — that
account is created automatically on boot if no user exists yet, and never
overwrites a password on later boots.

**Any time, including after the fact:**
```bash
# Inside Docker:
docker compose exec app python -m app.cli create-user <username>     # new login
docker compose exec app python -m app.cli reset-password <username>  # forgot it

# Outside Docker, same thing:
./scripts/create_user.sh <username>            # new login
./scripts/create_user.sh <username> --reset     # forgot it
```
(Password is always typed interactively, never as a command-line argument.)

## Deploy to Google Cloud

`deploy/gcp/` sets up a single Compute Engine VM running this same
`docker-compose.yml`, reachable only through an authenticated IAP tunnel —
no port is ever opened to the public internet, app included. See
[`deploy/gcp/README.md`](deploy/gcp/README.md) for the full walkthrough
(provisioning, redeploying, connecting BI tools remotely, backups). Fits
GCP's always-free tier for a personal, low-traffic ledger.

## Connect Power BI / Excel

Connect to PostgreSQL (`localhost`, database `libro`) and load:

| Object                | Role                                                    |
|-----------------------|---------------------------------------------------------|
| `v_fact_lines`        | the fact table — one row per journal line, fully described |
| `v_dim_account`       | account dimension with hierarchy path and normal side   |
| `v_dim_date`          | date dimension, 2020–2035                               |
| `v_monthly_activity`  | pre-aggregated account × month × scenario               |
| `fn_trial_balance('ACTUAL', '2026-08-31')` | trial balance at any date, any scenario |

Budget vs. actual in one query:

```sql
SELECT month, account_code, account_name,
       SUM(net) FILTER (WHERE scenario_code = 'ACTUAL')  AS actual,
       SUM(net) FILTER (WHERE scenario_code = 'BUD2026') AS budget
FROM v_monthly_activity
WHERE account_type = 'expense'
GROUP BY month, account_code, account_name
ORDER BY month, account_code;
```

## Project layout

```
db/schema.sql        the source of truth — tables, triggers, views, functions
db/seed.sql          starter chart of accounts + ACTUAL / BUD2026 scenarios
db/seed_demo.sql     optional sample entries
app/                 FastAPI app: HTML screens + /api/* JSON
app/auth.py          sessions, password hashing, CSRF, login rate-limit
app/cli.py           create-user / reset-password (see scripts/create_user.sh)
scripts/init_db.sh   local database bootstrap
scripts/create_user.sh  create or reset a login
deploy/gcp/          Google Cloud deployment (Compute Engine + IAP tunnel)
SPEC.md              design decisions and rationale
```

## API

`GET /api/trial-balance?scenario=ACTUAL&as_of=2026-08-31` ·
`GET /api/accounts` · `GET /api/scenarios` ·
`GET /api/entries?scenario=&date_from=&date_to=` ·
`GET /api/monthly-activity?scenario=`

## Tests

`tests/test_invariants.py` exercises the invariants in `SPEC.md` directly
against Postgres — balance enforcement, scenario locking, account
hierarchy, immutability, reversal integrity — so they hold regardless of
which client writes to the database. `tests/test_auth.py` drives the
actual FastAPI app instead, for the things only the app layer enforces:
login, session and CSRF checks, logout. Each run gets a disposable
`libro_test` database (dropped and recreated from `db/schema.sql` +
`db/seed.sql`).

With `docker compose up -d db` already running:

```bash
docker run --rm --network libro_default -v "$PWD":/srv/libro -w /srv/libro \
  python:3.12-slim bash -c "pip install -q -r requirements-dev.txt && pytest tests -v"
```

Or locally, with `psycopg[binary]` and `pytest` installed and `LIBRO_TEST_ADMIN_URL`
/ `LIBRO_TEST_URL` pointed at a reachable Postgres:

```bash
pip install -r requirements-dev.txt
pytest tests -v
```

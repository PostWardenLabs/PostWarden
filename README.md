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

Libro is built for one person running it on their own machine or home
network, and it currently has **no authentication** — every screen and
`/api/*` route (posting entries, reversing them, locking scenarios) is open
to anyone who can reach the app port. `docker-compose.yml` binds Postgres to
`127.0.0.1` for this reason (Power BI/Excel/psql on the same machine still
connect fine; the network can't). The app's own port (`8000`) has no such
guard — don't expose it beyond a trusted network without putting
authentication (e.g. a reverse proxy) in front of it, and change the
`libro`/`libro` credentials before you do. There's also no CSRF protection
on the POST forms; that becomes relevant the moment auth is added, so
revisit it then.

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
scripts/init_db.sh   local database bootstrap
deploy/gcp/          Google Cloud deployment (Compute Engine + IAP tunnel)
SPEC.md              design decisions and rationale
```

## API

`GET /api/trial-balance?scenario=ACTUAL&as_of=2026-08-31` ·
`GET /api/accounts` · `GET /api/scenarios` ·
`GET /api/entries?scenario=&date_from=&date_to=` ·
`GET /api/monthly-activity?scenario=`

## Tests

`tests/` exercises the invariants in `SPEC.md` directly against Postgres —
balance enforcement, scenario locking, account hierarchy, immutability,
reversal integrity — so they hold regardless of which client writes to the
database. Each run gets a disposable `libro_test` database (dropped and
recreated from `db/schema.sql` + `db/seed.sql`).

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

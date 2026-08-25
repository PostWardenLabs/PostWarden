# Libro

A personal general ledger where **the database guarantees the
accounting** — not the application, not the UI, the database. Real
double-entry bookkeeping, a proper chart of accounts, and
OneStream-style **scenarios** (your actual books, plus as many what-if
forecasts and budgets as you want) that never have to be reconciled
against each other because they're all just rows in the same tables.

PostgreSQL holds the truth and enforces every accounting rule itself,
at the database level, regardless of what wrote the data. A small
FastAPI app sits on top and gives you something pleasant to actually
use day to day. Power BI and Excel can connect straight to the database
through purpose-built reporting views, no export step required.

## What you get

- **A keyboard-first journal** — Tab through account → debit/credit →
  memo, a live balance bar, searchable account/tag/payee pickers,
  reusable entry templates, and one-click Reverse (history is
  append-only; you never edit a posted line).
- **Trial Balance, Income Statement, and Balance Sheet**, each with a
  real collapsible account hierarchy — a summary account like "Current
  Assets" shows the roll-up of everything beneath it, and every leaf
  amount is a link straight through to the exact journal postings
  behind it. Every report (and the Journal's own filters) refreshes the
  moment you change a scenario, date, or any other dropdown — no
  separate Refresh click.
- **A Budget grid** — an [Actual Budget](https://actualbudget.org)-style
  grid: type a number per account per month, watch every subtotal update
  live, see Actual and Variance right next to what you budgeted. No
  journal entries involved — a budget isn't a transaction, so it isn't
  modeled like one (see `SPEC.md` if you want the full argument).
- **Scenarios** for real forecasting too — a "what if I buy a house"
  scenario is a normal set of journal entries tagged with its own
  scenario code, so it can be a fully projected P&L *and* balance sheet,
  comparable to ACTUAL with a query, not a spreadsheet reconciliation.
- **Scheduled/recurring entries and CSV import**, both landing in a
  Staging scenario for review — a due occurrence or an imported row
  shows up for you to approve on one shared page, never posts to your
  real books unsupervised. Import round-trips the same column layout
  Export CSV produces, so export → edit in a spreadsheet → re-import is
  a real workflow.
- **CSV export everywhere**, a chart-of-accounts manager, payees, tags,
  and ten-odd hand-built visual themes if the default doesn't suit you.

## Why it exists

GnuCash stores in SQL but enforces nothing there — no foreign keys,
balance checked only in C++, key-value `slots` everywhere. Actual
Budget has a clean schema but is single-entry envelope budgeting at
heart. Libro takes the opposite bet: push every accounting invariant
into PostgreSQL itself, keep the application thin, and treat a scenario
as just a dimension on the same fact table so that *comparing two of
them is a query, not a module*.

What the database refuses to accept, no matter what client asks:

- an unbalanced entry in a scenario that enforces balance (checked at COMMIT
  by a deferred constraint trigger — the transaction simply fails)
- an entry with no lines
- a line posted to a summary or inactive account
- any edit or delete of a posted line (history is append-only; you reverse)
- an entry in a locked scenario, or any entry at all in a budget-only scenario
- a child account whose type differs from its parent, or a hierarchy cycle

## Why double-entry for *personal* finance?

The usual objection: double-entry is for businesses and accountants —
overkill for tracking your own money, where a spreadsheet of
transactions or a single-entry app (plain envelopes: money in, money
out) is simpler. It looks simpler right up until you want to ask your
tracking a second kind of question, and it turns out there was never
one system to ask — there were several ad hoc ones that happened to
agree so far.

Say you loan a friend $500. In a single-entry tracker that's... what,
exactly? An expense? A note in the memo field you'll have to remember to
search for later? Whatever you pick, "how much does everyone currently
owe me" isn't a number your tracker has — it's a number you'd
reconstruct by hand, by remembering which past transactions were loans
and adding them up again, every time you want to know. Now do the same
exercise for "what did I actually plan to spend on groceries this
month, and how far off was I" — in most personal finance tools that's a
second, disconnected feature (a "budget" screen) that has to be kept in
sync with the transaction list by hand or by an importer's best guess,
because nothing about *how the data is modeled* ties the two together.

Double-entry fixes this not by adding rigor for its own sake, but by
giving every one of those questions the same answer: **an account**.
Money someone owes you isn't a memo, it's an Accounts Receivable
account — loan the $500 (debit A/R, credit Cash) and its balance *is*
"how much they owe me," always current, no reconstruction. Pay a bill
you'll be reimbursed for later and the reimbursement isn't a mental
asterisk on an expense, it's Accounts Payable or A/R behaving exactly
like any other account. A budget isn't a separate feature bolted onto
the transaction list — in Libro specifically, it's the same data model
with a second dimension (`scenario`) added, so "actual vs. budget" is a
`GROUP BY` with two filters, and it's *why* Libro's own Budget grid can
show Actual and Variance next to what you typed without a reconciliation
step gluing two systems together. An income statement isn't a workbook
you maintain in parallel — it's a query over Income and Expense
accounts, always in sync with the ledger because it's not a copy of the
ledger, it's a view of it. Net worth isn't "let me go check six
balances and hope I didn't forget the credit card" — it's Assets minus
Liabilities, correct by construction.

None of this asks you to think like an accountant day to day. Entering
a transaction takes the same one action either way — you're recording
the coffee purchase regardless — double-entry just also asks *where the
money came from* (Checking, in this case), which New entry's keyboard
flow (account, debit or credit, Tab) makes about as much extra effort as
picking a category already is in a single-entry app. What you get for
that one extra field is the thing single-entry can't give you at any
price: every report is a query against one source of truth instead of a
reconciliation project between however many separate views of your
money you've accumulated. The "complexity" isn't overhead you pay for
nothing — it's the complexity you were always going to hit eventually
(reconciling a budget against actuals, tracking who owes whom), paid
once, up front, as a data model, instead of over and over by hand.

## Quickstart (Docker)

```bash
docker compose up --build
```

Then open http://localhost:8000, and see "Creating a login" below — no
login exists until you make one. The database initializes itself on
first boot: schema, a starter chart of accounts, and a few demo entries
(remove the `03_seed_demo.sql` line in `docker-compose.yml` for a
completely clean start).

Postgres is exposed on `localhost:5432` (user/db/password: `libro`) so
Power BI, Excel, or `psql` can connect directly alongside the app.

## Run it (local, no Docker)

Requires PostgreSQL 14+ and Python 3.11+.

```bash
./scripts/init_db.sh --with-demo     # create + load the database
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Set `DATABASE_URL` if your Postgres isn't `libro:libro@localhost:5432/libro`.

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

## Documentation

Start with this README for orientation, then:

| Doc | For |
|---|---|
| [`SPEC.md`](SPEC.md) | Design decisions and the reasoning behind them — read this before changing how anything is modeled. |
| [`docs/SCHEMA.md`](docs/SCHEMA.md) | The entity-relationship diagram and a table-by-table reference. |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | How the FastAPI app, templates, and JS are organized, and the UI patterns reused across screens. |
| [`deploy/gcp/README.md`](deploy/gcp/README.md) | Deploying to Google Cloud — provisioning, redeploying, backups, remote BI access. |

[`docs/README.md`](docs/README.md) is the short map tying those together
if you'd rather start there.

## Security notes

Every screen and `/api/*` route requires a login — see "Creating a login"
above. A session is an opaque random token stored in Postgres
(`sessions`, checked on every request); logging out or resetting a
password deletes it, no signing secret to manage. State-changing POSTs
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

Budget vs. actual in one query (a *full* budget-like scenario — see
`SPEC.md` decision 3 for the income-statement-only kind, which lives in
`budget_lines` instead of `v_monthly_activity`):

```sql
SELECT month, account_code, account_name,
       SUM(net) FILTER (WHERE scenario_code = 'ACTUAL')  AS actual,
       SUM(net) FILTER (WHERE scenario_code = 'FCST_2026') AS forecast
FROM v_monthly_activity
WHERE account_type = 'expense'
GROUP BY month, account_code, account_name
ORDER BY month, account_code;
```

## Project layout

```
db/schema.sql             the source of truth — tables, triggers, views, functions
db/seed.sql               starter chart of accounts + ACTUAL / STAGING / BUD2026 scenarios
db/seed_demo.sql          optional sample entries

app/main.py               every route — see docs/ARCHITECTURE.md for the section map
app/auth.py               sessions, password hashing, CSRF, login rate-limit
app/db.py                 the psycopg3 connection pool
app/cli.py                create-user / reset-password (see scripts/create_user.sh)
app/templates/            one Jinja2 template per screen, all extending base.html
app/static/               one small JS file per progressive enhancement, plus style.css

tests/test_invariants.py  the schema's own rules, asserted straight against Postgres
tests/test_auth.py        the app layer — routes, sessions, CSRF, rendering

scripts/init_db.sh        local database bootstrap
scripts/create_user.sh    create or reset a login
deploy/gcp/               Google Cloud deployment (Compute Engine + IAP tunnel)

SPEC.md                   design decisions and rationale
docs/                     schema reference + ERD, app architecture — see docs/README.md
CLAUDE.md                 instructions for an AI coding agent working in this repo
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

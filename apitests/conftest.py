"""Fixtures for tests that need a real Postgres connection — currently
just `modules/reports/`. `domain/` tests need no database at all (that's
the whole point of `domain/`); `test_config.py`/`test_db.py`'s own DB
check is a one-off manual smoke test outside the suite (see
REBUILD_STATUS.md's Phase 1.2 log entry), not something this file needs
to support.

`DATABASE_URL` (same env var `config.py`/`db.py` read, `backend-ci.yml`
already sets it) names which Postgres *server* to reach — host, port,
credentials — not the database to run tests against directly. This file
carves out its own disposable scratch database on that same server
(`postwarden_backend_test`, dropped and recreated every run, loaded from
`db/schema.sql` alone — **no** `seed.sql`/`seed_demo.sql`), mirroring
`tests/conftest.py`'s own scratch-db pattern. This directory is a
top-level sibling of `tests/`, not `tests/api/` — pytest loads every
conftest.py from the repo root down to each collected path, so nesting
under `tests/` would mean `tests/conftest.py`'s own `pytest_configure`
(which tries to reach a `db` hostname that doesn't exist outside
Docker) fires on every run of this suite too, even one that never
selects any of `tests/`' own tests. Found the hard way, post-cutover-
promotion, when `pytest apitests -q` — run from a real host shell, not
a container — failed before collecting a single test.
Schema only, deliberately: every `modules/reports/` test builds its own
minimal fixture rows (`mk_account`/`mk_scenario`/`mk_entry`/`mk_line`
below, adapted from the root conftest's psycopg-cursor helpers to a
SQLAlchemy `Connection`) rather than relying on `seed.sql`'s real chart
of accounts, so there's no risk of a test's own account code colliding
with one seed.sql already defined. This also means these tests work the
same way locally (`docker compose up -d db`, which loads the *main*
`postwarden` database with schema + both seed files — untouched by this
file, since it only ever creates/uses its own separate
`postwarden_backend_test`) and in CI (`backend-ci.yml`'s
Postgres service container, schema-only, no seed step at all): either
way, this file's own `pytest_configure` establishes the scratch database
itself, from `db/schema.sql`, before collection.

The `postwarden` role docker-compose/CI both create is the Postgres
image's `POSTGRES_USER` — a superuser by default in the official image
— which is what lets `pytest_configure` `DROP`/`CREATE DATABASE` at all.

The `conn` fixture never commits: each test gets its own transaction,
rolled back at teardown, so the scratch database stays empty between
tests even though `pytest_configure` only creates it once per run. This
also means the row-level triggers that are genuinely `DEFERRABLE
INITIALLY DEFERRED` (`trg_lines_balanced`, `trg_entry_has_lines` —
SPEC.md decision 2) never actually fire in these tests, since deferred
triggers run at COMMIT; harmless here, since these tests exercise report
*reads* against fixtures this file already builds correctly, not the
invariants those triggers enforce (that's `tests/test_invariants.py`'s
job, at the repo root, unchanged by this branch). Every *immediate*
trigger (hierarchy, account-type-guard, scenario-lock, income-statement-
only) still fires normally within the open transaction, same as it
would at real runtime.
"""
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

ROOT = Path(__file__).resolve().parent.parent  # apitests/conftest.py -> repo root
TEST_DB = "postwarden_backend_test"

_base = urlsplit(os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://postwarden:postwarden@localhost:5432/postwarden"
))
# psycopg.connect() (the one-time DROP/CREATE DATABASE below) wants the
# plain "postgresql://" scheme; SQLAlchemy's create_engine() wants the
# "+psycopg" dialect suffix — same distinction config.py's own comment on
# database_url draws, just needed in both directions here.
ADMIN_URL = urlunsplit(_base._replace(scheme="postgresql", path="/postgres"))
PSYCOPG_TEST_URL = urlunsplit(_base._replace(scheme="postgresql", path=f"/{TEST_DB}"))
SQLA_TEST_URL = urlunsplit(_base._replace(scheme="postgresql+psycopg", path=f"/{TEST_DB}"))


def pytest_configure(config):
    """Runs before test collection — (re)creates the scratch database
    from `db/schema.sql` alone. See this module's own docstring for why
    schema-only, no seed."""
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    schema_sql = (ROOT / "db" / "schema.sql").read_text()
    with psycopg.connect(PSYCOPG_TEST_URL, autocommit=True) as conn:
        conn.execute(schema_sql)


@pytest.fixture(scope="session")
def _engine():
    return create_engine(SQLA_TEST_URL, pool_pre_ping=True)


@pytest.fixture
def conn(_engine) -> Connection:
    """One Connection per test, one transaction, always rolled back."""
    with _engine.connect() as c:
        yield c
        c.rollback()


def mk_account_level(conn: Connection, name: str, depth: int) -> dict:
    row = conn.execute(
        text("INSERT INTO account_levels (name, depth) VALUES (:name, :depth) RETURNING id, depth"),
        {"name": name, "depth": depth},
    ).mappings().one()
    return dict(row)


def mk_scenario(conn: Connection, code: str, *, scenario_type: str = "actual", enforce_balance: bool = True,
                income_statement_only: bool = False, is_staging: bool = False,
                base_level_id: int | None = None) -> dict:
    row = conn.execute(text("""
        INSERT INTO scenarios (code, name, scenario_type, enforce_balance, income_statement_only,
                                is_staging, base_level_id)
        VALUES (:code, :name, :scenario_type, :enforce_balance, :income_statement_only,
                :is_staging, :base_level_id)
        RETURNING id, code
    """), {"code": code, "name": f"Test scenario {code}", "scenario_type": scenario_type,
            "enforce_balance": enforce_balance, "income_statement_only": income_statement_only,
            "is_staging": is_staging, "base_level_id": base_level_id}).mappings().one()
    return dict(row)


def mk_account(conn: Connection, code: str, name: str, account_type: str, *, parent_id: int | None = None,
               is_postable: bool = True, is_cashflow: bool = False) -> dict:
    row = conn.execute(text("""
        INSERT INTO accounts (code, name, account_type, parent_id, is_postable, is_cashflow)
        VALUES (:code, :name, :account_type, :parent_id, :is_postable, :is_cashflow)
        RETURNING id, code
    """), {"code": code, "name": name, "account_type": account_type, "parent_id": parent_id,
            "is_postable": is_postable, "is_cashflow": is_cashflow}).mappings().one()
    return dict(row)


def mk_entry(conn: Connection, scenario_id: int, entry_date: str, description: str = "Test entry", *,
             reference: str | None = None, payee_id: int | None = None,
             scheduled_entry_id: int | None = None, import_batch_id: int | None = None,
             promoted_entry_id: str | None = None) -> str:
    """The last four keyword-only params default to `None` (the original
    four-positional-arg shape every existing caller uses still works
    unchanged) — added for `modules/staging/`'s own tests, which need a
    `journal_entries` row that's actually eligible to sit in the Staging
    scenario: `fn_staging_manual_entry_guard` (`db/schema.sql`) rejects a
    staging-scenario insert with neither `scheduled_entry_id` nor
    `import_batch_id` set, so a bare `mk_entry(conn, staging_id, ...)`
    would fail for those tests without this."""
    row = conn.execute(text("""
        INSERT INTO journal_entries (scenario_id, entry_date, description, reference, payee_id,
                                      scheduled_entry_id, import_batch_id, promoted_entry_id)
        VALUES (:scenario_id, :entry_date, :description, :reference, :payee_id,
                :scheduled_entry_id, :import_batch_id, :promoted_entry_id)
        RETURNING id
    """), {"scenario_id": scenario_id, "entry_date": entry_date, "description": description,
           "reference": reference, "payee_id": payee_id, "scheduled_entry_id": scheduled_entry_id,
           "import_batch_id": import_batch_id, "promoted_entry_id": promoted_entry_id}).mappings().one()
    return row["id"]


def mk_line(conn: Connection, entry_id: str, account_id: int, amount, line_no: int) -> None:
    conn.execute(text("""
        INSERT INTO journal_lines (entry_id, line_no, account_id, amount)
        VALUES (:entry_id, :line_no, :account_id, :amount)
    """), {"entry_id": entry_id, "line_no": line_no, "account_id": account_id, "amount": amount})


def mk_budget_line(conn: Connection, scenario_id: int, account_id: int, amount, period_month: str) -> int:
    """A `budget_lines` row — needed for `modules/budget/`'s own tests,
    which build an income-statement-only scenario's figures directly
    rather than through `POST /budget/cell` (that route's own coverage is
    the point of `test_router.py`'s upsert test)."""
    row = conn.execute(text("""
        INSERT INTO budget_lines (scenario_id, account_id, period_month, amount)
        VALUES (:scenario_id, :account_id, :period_month, :amount)
        RETURNING id
    """), {"scenario_id": scenario_id, "account_id": account_id, "period_month": period_month,
           "amount": amount}).mappings().one()
    return row["id"]


def mk_user(conn: Connection) -> dict:
    """A real `users` row — needed as of Phase 1.14, whose write-route
    tests (`modules/entries/`, `/staging/`, `/imports/`) fake a logged-in
    session by overriding `get_current_session`/`require_csrf_header`
    directly rather than a real login, but still thread that session's
    `user_id` into `created_by_user_id`/`imported_by_user_id` for real —
    a bare made-up int like `1` would violate those columns' own FK
    against `users(id)` in a scratch database that starts with none.
    Username is random per call (`users.username` is UNIQUE) since some
    tests call `client_for(conn)`, and so this, more than once."""
    row = conn.execute(
        text("INSERT INTO users (username, password_hash) VALUES (:username, 'x') "
             "RETURNING id, username"),
        {"username": f"test-{secrets.token_hex(4)}"},
    ).mappings().one()
    return dict(row)

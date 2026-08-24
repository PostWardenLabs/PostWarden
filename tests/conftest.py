"""Fixtures for the invariant test suite.

These tests talk directly to Postgres — no FastAPI involved — because the
thing under test is "does the database enforce what SPEC.md claims," not
the app. Every test run gets a disposable database (dropped and recreated
from db/schema.sql + db/seed.sql), so tests are free to commit real rows.

Point LIBRO_TEST_ADMIN_URL at a superuser-ish connection (able to
CREATE/DROP DATABASE) and LIBRO_TEST_URL at the disposable database itself;
both default to the docker-compose "db" service.
"""
import os
import random
import string
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

ROOT = Path(__file__).parent.parent
TEST_DB = "libro_test"
ADMIN_URL = os.environ.get(
    "LIBRO_TEST_ADMIN_URL", "postgresql://libro:libro@db:5432/postgres"
)
TEST_URL = os.environ.get(
    "LIBRO_TEST_URL", f"postgresql://libro:libro@db:5432/{TEST_DB}"
)

# app/db.py opens its connection pool at import time, so DATABASE_URL has to
# point at the disposable test database *before* anything imports app.main
# (e.g. tests/test_auth.py) — which means before pytest even collects test
# modules, not inside a fixture (fixtures run after collection/import).
os.environ.setdefault("DATABASE_URL", TEST_URL)


def pytest_configure(config):
    """Runs before test collection — see the DATABASE_URL comment above for
    why this can't just be a fixture."""
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f"DROP DATABASE IF EXISTS {TEST_DB} WITH (FORCE)")
        admin.execute(f"CREATE DATABASE {TEST_DB}")
    schema_sql = (ROOT / "db" / "schema.sql").read_text()
    seed_sql = (ROOT / "db" / "seed.sql").read_text()
    with psycopg.connect(TEST_URL, autocommit=True) as conn:
        conn.execute(schema_sql)
        conn.execute(seed_sql)


@pytest.fixture
def conn():
    with psycopg.connect(TEST_URL, row_factory=dict_row) as c:
        yield c


@contextmanager
def expect_error(conn, match=None):
    """Assert the wrapped block raises a Postgres error, then clean up the
    aborted transaction so the connection is usable again."""
    with pytest.raises(psycopg.Error) as exc_info:
        yield
    conn.rollback()
    if match:
        assert match.lower() in str(exc_info.value).lower(), str(exc_info.value)


def rand_account_code() -> str:
    return "".join(random.choices(string.digits, k=6))


def rand_scenario_code() -> str:
    return "T" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))


def mk_account(cur, account_type="asset", parent_id=None, postable=True,
               active=True, code=None) -> dict:
    code = code or rand_account_code()
    cur.execute(
        """INSERT INTO accounts (code, name, account_type, parent_id,
                                  is_postable, is_active)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING id, code""",
        (code, f"Test account {code}", account_type, parent_id, postable, active))
    return cur.fetchone()


def mk_scenario(cur, scenario_type="budget", enforce_balance=True,
                is_locked=False, code=None) -> dict:
    code = code or rand_scenario_code()
    cur.execute(
        """INSERT INTO scenarios (code, name, scenario_type, enforce_balance,
                                   is_locked)
           VALUES (%s, %s, %s, %s, %s) RETURNING id, code""",
        (code, f"Test scenario {code}", scenario_type, enforce_balance, is_locked))
    return cur.fetchone()


def mk_entry(cur, scenario_id, description="Test entry") -> int:
    cur.execute(
        """INSERT INTO journal_entries (scenario_id, entry_date, description)
           VALUES (%s, CURRENT_DATE, %s) RETURNING id""",
        (scenario_id, description))
    return cur.fetchone()["id"]


def mk_line(cur, entry_id, account_id, amount, line_no=1, memo=None):
    cur.execute(
        """INSERT INTO journal_lines (entry_id, line_no, account_id, amount, memo)
           VALUES (%s, %s, %s, %s, %s)""",
        (entry_id, line_no, account_id, amount, memo))


@pytest.fixture
def actual_scenario_id(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        return cur.fetchone()["id"]


def mk_user(cur, username=None, password="testpass123") -> dict:
    from app.auth import hash_password
    username = username or ("user" + "".join(random.choices(string.digits, k=6)))
    cur.execute(
        "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id, username",
        (username, hash_password(password)))
    row = cur.fetchone()
    return {"id": row["id"], "username": row["username"], "password": password}

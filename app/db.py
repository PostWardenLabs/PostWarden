"""Database access for PostWarden — a thin layer over psycopg3.

No ORM on purpose: db/schema.sql is the source of truth, and every query in
the app is plain SQL you can read, run in psql, or paste into Power BI.
"""
import os
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://libro:libro@localhost:5432/libro"
)

pool = ConnectionPool(
    DATABASE_URL,
    min_size=1,
    max_size=8,
    kwargs={"row_factory": dict_row},
    open=True,
)


def q(sql: str, params=None):
    """Run a read query, return list[dict]."""
    with pool.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            if cur.description is None:
                return []
            return cur.fetchall()


def q1(sql: str, params=None):
    """Run a read query, return the first row (dict) or None."""
    rows = q(sql, params)
    return rows[0] if rows else None


@contextmanager
def tx():
    """A transaction: yields a cursor; commits on success, rolls back on error.

    The deferred constraint triggers fire at COMMIT — meaning an unbalanced
    journal entry raises *here*, when the transaction tries to close, and the
    whole entry (header + lines) vanishes atomically.
    """
    with pool.connection() as conn:
        with conn.cursor() as cur:
            yield cur
        # leaving the connection context commits; psycopg rolls back on error

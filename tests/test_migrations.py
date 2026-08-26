"""app/migrate.py — the mechanism, not any specific migration (there isn't
one yet; db/schema.sql is still the only version). Uses real files on disk
against the real test database, same as everything else here — nothing
about this module is mocked, since the whole point is that it's what
actually runs at app startup against a real Postgres.
"""
import psycopg
import pytest

from app import migrate


def _write_migration(tmp_path, number, sql):
    f = tmp_path / f"{number:03d}_test.sql"
    f.write_text(sql)
    return f


def test_pending_migrations_filters_and_orders_by_number(tmp_path, monkeypatch):
    _write_migration(tmp_path, 2, "SELECT 1;")
    _write_migration(tmp_path, 10, "SELECT 1;")
    _write_migration(tmp_path, 1, "SELECT 1;")
    (tmp_path / "README.md").write_text("not a migration")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)

    files = migrate.pending_migrations(current=1)
    assert [f.name for f in files] == ["002_test.sql", "010_test.sql"]

    assert migrate.pending_migrations(current=10) == []


def test_run_migrations_applies_pending_and_advances_version(conn, tmp_path, monkeypatch):
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_version")
        baseline = cur.fetchone()["version"]
    conn.commit()

    _write_migration(tmp_path, baseline + 1,
                      "CREATE TABLE _migration_test_table (id INT);")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)

    try:
        migrate.run_migrations()

        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_version")
            assert cur.fetchone()["version"] == baseline + 1
            cur.execute("SELECT to_regclass('_migration_test_table') AS t")
            assert cur.fetchone()["t"] == "_migration_test_table"
        conn.commit()

        # Re-running with nothing new pending is a no-op, not an error —
        # this is exactly what happens on every ordinary app restart.
        migrate.run_migrations()
        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_version")
            assert cur.fetchone()["version"] == baseline + 1
        conn.commit()
    finally:
        with conn.cursor() as cur:
            cur.execute("DROP TABLE IF EXISTS _migration_test_table")
            cur.execute("UPDATE schema_version SET version = %s", (baseline,))
        conn.commit()


def test_a_failed_migration_does_not_advance_the_version(conn, tmp_path, monkeypatch):
    with conn.cursor() as cur:
        cur.execute("SELECT version FROM schema_version")
        baseline = cur.fetchone()["version"]
    conn.commit()

    _write_migration(tmp_path, baseline + 1, "THIS IS NOT VALID SQL;")
    monkeypatch.setattr(migrate, "MIGRATIONS_DIR", tmp_path)

    try:
        with pytest.raises(psycopg.Error):
            migrate.run_migrations()

        with conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_version")
            assert cur.fetchone()["version"] == baseline
        conn.commit()
    finally:
        with conn.cursor() as cur:
            cur.execute("UPDATE schema_version SET version = %s", (baseline,))
        conn.commit()

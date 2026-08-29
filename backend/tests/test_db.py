"""Unit tests for postwarden.db — engine construction only. No live
Postgres: SQLAlchemy's create_engine() doesn't open a connection until
something actually queries through it, so these stay in the same
no-database tier as tests/domain/.
"""
from postwarden.config import get_settings
from postwarden.db import get_engine


def test_get_engine_uses_the_psycopg_dialect_and_settings_url(monkeypatch):
    get_settings.cache_clear()
    get_engine.cache_clear()
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@dbhost:5432/postwarden_test")
    engine = get_engine()
    assert engine.url.drivername == "postgresql+psycopg"
    assert engine.url.host == "dbhost"
    assert engine.url.database == "postwarden_test"
    get_settings.cache_clear()
    get_engine.cache_clear()


def test_get_engine_is_cached(monkeypatch):
    get_settings.cache_clear()
    get_engine.cache_clear()
    assert get_engine() is get_engine()
    get_settings.cache_clear()
    get_engine.cache_clear()

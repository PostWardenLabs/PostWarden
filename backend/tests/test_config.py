"""Unit tests for postwarden.config — env vars only, no database."""
from postwarden.config import Settings, get_settings


def test_defaults_match_legacy_app_db_defaults(monkeypatch):
    for var in (
        "DATABASE_URL",
        "POSTWARDEN_COOKIE_SECURE",
        "POSTWARDEN_ADMIN_USER",
        "POSTWARDEN_ADMIN_PASSWORD",
        "POSTWARDEN_DEMO_MODE",
        "POSTWARDEN_BI_PORT",
    ):
        monkeypatch.delenv(var, raising=False)
    settings = Settings()
    assert settings.database_url == "postgresql+psycopg://postwarden:postwarden@localhost:5432/postwarden"
    assert settings.postwarden_cookie_secure is False
    assert settings.postwarden_admin_user == ""
    assert settings.postwarden_admin_password == ""
    assert settings.postwarden_demo_mode is False
    assert settings.postwarden_bi_port == "5432"


def test_database_url_reads_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@dbhost:5432/postwarden_test")
    assert Settings().database_url == "postgresql+psycopg://u:p@dbhost:5432/postwarden_test"


def test_bool_fields_accept_the_same_truthy_spellings_legacy_used(monkeypatch):
    for truthy in ("1", "true", "True", "yes", "YES"):
        monkeypatch.setenv("POSTWARDEN_DEMO_MODE", truthy)
        assert Settings().postwarden_demo_mode is True, truthy


def test_bool_fields_default_false_on_empty_or_unset(monkeypatch):
    monkeypatch.setenv("POSTWARDEN_COOKIE_SECURE", "")
    assert Settings().postwarden_cookie_secure is False


def test_get_settings_is_cached(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("POSTWARDEN_BI_PORT", "6432")
    first = get_settings()
    second = get_settings()
    assert first is second
    assert first.postwarden_bi_port == "6432"
    get_settings.cache_clear()

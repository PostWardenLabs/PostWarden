"""Tests of `main.py` itself — the app factory. Three things are new as
of Phase 1.14 and none of them are covered by any module's own tests:

1. **Every module's router is actually mounted into the real `app`
   object**, not just built and tested in isolation the way every
   module's own `test_router.py` proved through Phase 1.13.
2. **The Phase 1.14 auth wiring holds through the real `app`**, not just
   each module's own throwaway `FastAPI()` + `include_router()` (which,
   as of this phase, overrides `get_current_session`/`require_csrf_
   header` directly — proving the dependency is *present*, not that
   `main.py` actually leaves it enabled when mounting for real).
3. **The two bits of real logic `main.py` itself adds**: the `lifespan`
   admin-bootstrap hook, and the `advance_due_schedules` middleware.

`app_client`, below, points the *real* `postwarden.main.app`'s `get_
connection` dependency at this test's own rolled-back scratch
transaction (the same `conn` fixture every other module's tests use) —
a second throwaway `FastAPI()` would prove nothing about `main.py`
itself. `get_settings`/`get_engine` are deliberately left alone for
those tests: nothing they exercise needs a real Postgres connection for
anything but `get_current_session`'s own `sessions` lookup, which the
`get_connection` override already covers — touching the real, cached
`get_engine()` would mean either the developer's own local `postwarden`
database (running this suite locally against `docker compose up -d db`)
or CI's schema-only service container, neither of which this file has
any business writing to.

The `lifespan`/`advance_due_schedules` tests below take the opposite
approach for the same reason: they monkeypatch `main.get_engine` itself
to a fake that can't touch any real database at all, since proving
`main.py`'s own plumbing ("call this, with these arguments, only under
these conditions") doesn't need a real connection — `bootstrap_admin_
from_env`'s and `materialize_due_schedules`' own logic already have
their own real-Postgres tests in `modules/auth/`'s and `modules/
scheduling/`'s own test suites (Phases 1.11, 1.10).
"""
import pytest
from fastapi.testclient import TestClient

from postwarden import main
from postwarden.config import Settings, get_settings
from postwarden.db import get_connection
from postwarden.modules.auth.deps import SESSION_COOKIE


@pytest.fixture(autouse=True)
def _reset_overrides():
    yield
    main.app.dependency_overrides.clear()


def app_client(conn) -> TestClient:
    main.app.dependency_overrides[get_connection] = lambda: conn
    return TestClient(main.app)


# ---------------------------------------------------------------------------
# Router mounting + the auth wiring holding through the real app
# ---------------------------------------------------------------------------

def test_every_module_is_mounted():
    # One representative route per module actually included into `app` —
    # not exhaustive (see each module's own test_router.py for that),
    # just proof every module made it into the real app, not only its
    # own isolated test.
    paths = set(main.app.openapi()["paths"])
    for path in ("/login", "/reports/trial-balance", "/entries", "/staging",
                 "/import", "/budget", "/accounts", "/scheduled",
                 "/api/trial-balance", "/settings/connect-bi"):
        assert path in paths, path


def test_login_is_reachable_with_no_session_at_all(conn):
    # The one route that must NOT 401 from the session gate itself — a
    # bad login answers its own 401 (`modules/auth/router.py`), not one
    # from a router-level dependency blocking the request before it ever
    # runs.
    resp = app_client(conn).post("/login", json={"username": "nobody", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid username or password"


def test_a_protected_get_route_401s_with_no_session(conn):
    resp = app_client(conn).get("/reports/trial-balance")
    assert resp.status_code == 401


def test_a_protected_write_route_401s_with_no_session(conn):
    resp = app_client(conn).post("/accounts", json={
        "code": "9999", "name": "X", "account_type": "asset",
    })
    assert resp.status_code == 401


def test_analytics_api_route_401s_with_no_session(conn):
    # /api/* answered a bare unauthenticated request with a JSON 401 in
    # legacy too (`auth_gate`'s own `path.startswith("/api/")` branch) —
    # confirms that didn't quietly change shape moving to a per-route
    # dependency.
    resp = app_client(conn).get("/api/accounts")
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# GET /config — Phase 3.1's public, unauthenticated app-metadata route.
# ---------------------------------------------------------------------------

def _config_client(settings: Settings) -> TestClient:
    main.app.dependency_overrides[get_settings] = lambda: settings
    return TestClient(main.app)


def test_config_reads_version_from_the_configured_file(tmp_path):
    version_file = tmp_path / "VERSION"
    version_file.write_text("9.9.9\n")
    resp = _config_client(Settings(POSTWARDEN_VERSION_FILE=version_file)).get("/config")
    assert resp.status_code == 200
    assert resp.json()["version"] == "9.9.9"


def test_config_version_is_blank_not_a_500_when_the_file_is_missing(tmp_path):
    resp = _config_client(Settings(POSTWARDEN_VERSION_FILE=tmp_path / "nope")).get("/config")
    assert resp.status_code == 200
    assert resp.json()["version"] == ""


def test_config_omits_demo_credentials_when_demo_mode_is_off(tmp_path):
    settings = Settings(POSTWARDEN_VERSION_FILE=tmp_path / "nope",
                         POSTWARDEN_DEMO_MODE=False,
                         POSTWARDEN_ADMIN_USER="david", POSTWARDEN_ADMIN_PASSWORD="secret")
    resp = _config_client(settings).get("/config")
    body = resp.json()
    # The security-relevant case this route's own docstring calls out:
    # an admin user/password can be set on *any* Docker deployment (it's
    # what bootstraps the first account), not just a demo one — those
    # must never reach an unauthenticated caller unless demo_banner is
    # genuinely on.
    assert body["demo_banner"] is False
    assert body["demo_user"] is None
    assert body["demo_password"] is None


def test_config_includes_demo_credentials_when_demo_mode_is_on(tmp_path):
    settings = Settings(POSTWARDEN_VERSION_FILE=tmp_path / "nope",
                         POSTWARDEN_DEMO_MODE=True,
                         POSTWARDEN_ADMIN_USER="david", POSTWARDEN_ADMIN_PASSWORD="secret")
    resp = _config_client(settings).get("/config")
    body = resp.json()
    assert body["demo_banner"] is True
    assert body["demo_user"] == "david"
    assert body["demo_password"] == "secret"


# ---------------------------------------------------------------------------
# advance_due_schedules — the one piece of legacy's auth_gate middleware
# main.py still carries (see main.py's own docstring for why the rest of
# auth_gate didn't move here as middleware).
# ---------------------------------------------------------------------------

class _FakeConn:
    def begin(self):
        class _NullTxn:
            def __enter__(self_inner):
                return None

            def __exit__(self_inner, *exc):
                return False
        return _NullTxn()


class _FakeEngine:
    def connect(self):
        class _Ctx:
            def __enter__(self_inner):
                return _FakeConn()

            def __exit__(self_inner, *exc):
                return False
        return _Ctx()


def test_advance_due_schedules_skips_entirely_with_no_session_cookie(monkeypatch):
    # No cookie at all means no reason to open a connection in the first
    # place — proven by making get_engine() itself raise if called.
    def _boom():
        raise AssertionError("should not touch the database with no session cookie")
    monkeypatch.setattr(main, "get_engine", _boom)
    resp = TestClient(main.app).get("/healthz")
    assert resp.status_code == 200


def test_advance_due_schedules_skips_when_the_session_is_invalid(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(main.auth_service, "get_session", lambda conn, token: None)
    monkeypatch.setattr(main.scheduling_service, "materialize_due_schedules",
                         lambda conn: calls.append(conn))
    client = TestClient(main.app)
    client.cookies.set(SESSION_COOKIE, "not-a-real-token")
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert calls == []


def test_advance_due_schedules_calls_materialize_when_the_session_is_valid(monkeypatch):
    calls = []
    monkeypatch.setattr(main, "get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(main.auth_service, "get_session", lambda conn, token: {"user_id": 1})
    monkeypatch.setattr(main.scheduling_service, "materialize_due_schedules",
                         lambda conn: calls.append(conn))
    client = TestClient(main.app)
    client.cookies.set(SESSION_COOKIE, "a-real-looking-token")
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert len(calls) == 1


def test_advance_due_schedules_swallows_a_failure_same_as_legacy(monkeypatch):
    # "A failure here shouldn't take the app down" — same bare
    # `except Exception: pass` legacy's own auth_gate uses.
    monkeypatch.setattr(main, "get_engine", lambda: _FakeEngine())
    monkeypatch.setattr(main.auth_service, "get_session", lambda conn, token: {"user_id": 1})

    def _boom(conn):
        raise RuntimeError("a schedule blew up")
    monkeypatch.setattr(main.scheduling_service, "materialize_due_schedules", _boom)
    client = TestClient(main.app)
    client.cookies.set(SESSION_COOKIE, "a-real-looking-token")
    resp = client.get("/healthz")
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# lifespan — the admin-bootstrap hook
# ---------------------------------------------------------------------------

def test_lifespan_calls_bootstrap_admin_from_env_with_settings_values(monkeypatch):
    monkeypatch.setattr(main, "get_engine", lambda: _FakeEngine())
    calls = []
    monkeypatch.setattr(main.auth_service, "bootstrap_admin_from_env",
                         lambda conn, username, password: calls.append((username, password)))
    monkeypatch.setenv("POSTWARDEN_ADMIN_USER", "david")
    monkeypatch.setenv("POSTWARDEN_ADMIN_PASSWORD", "secret")
    main.get_settings.cache_clear()
    try:
        with TestClient(main.app):
            pass
    finally:
        main.get_settings.cache_clear()
    assert calls == [("david", "secret")]

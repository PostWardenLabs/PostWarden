"""Exercises the app-level auth: login, session/CSRF enforcement, logout.

Unlike test_invariants.py, this drives the actual FastAPI app (TestClient),
since these are things only the app layer enforces — the schema just holds
the users/sessions rows it checks against.
"""
from fastapi.testclient import TestClient

from app.main import app
from conftest import mk_user

client_kwargs = {"base_url": "http://testserver", "follow_redirects": False}


def test_unauthenticated_html_redirects_to_login(conn):
    with TestClient(app, **client_kwargs) as c:
        r = c.get("/")
        assert r.status_code == 303
        assert r.headers["location"] == "/login"


def test_unauthenticated_api_returns_401(conn):
    with TestClient(app, **client_kwargs) as c:
        r = c.get("/api/accounts")
        assert r.status_code == 401


def test_login_wrong_password_fails(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        r = c.post("/login", data={"username": user["username"], "password": "nope"})
        assert r.status_code == 303
        assert r.headers["location"].startswith("/login?err=")
        assert "libro_session" not in c.cookies


def test_login_correct_succeeds_and_grants_access(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        r = c.post("/login", data={"username": user["username"], "password": user["password"]})
        assert r.status_code == 303
        assert r.headers["location"] == "/"
        assert "libro_session" in c.cookies

        r = c.get("/")
        assert r.status_code == 200
        assert "Trial balance" in r.text


def test_inactive_user_cannot_log_in(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        cur.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (user["id"],))
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        r = c.post("/login", data={"username": user["username"], "password": user["password"]})
        assert r.headers["location"].startswith("/login?err=")
        assert "libro_session" not in c.cookies


def test_post_without_csrf_token_is_rejected(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        # csrf_token is a required Form(...) field, so omitting it entirely
        # never even reaches require_csrf — FastAPI's own validation
        # rejects it first (422), which still blocks the request just as
        # effectively as the flash-redirect path a wrong-but-present token
        # takes (see test_post_with_forged_csrf_token_is_rejected).
        r = c.post("/accounts", data={
            "code": "9991", "name": "No CSRF", "account_type": "asset",
        })
        assert r.status_code == 422

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM accounts WHERE code = '9991'")
        assert cur.fetchone() is None


def test_post_with_forged_csrf_token_is_rejected(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.post("/accounts", data={
            "code": "9992", "name": "Forged CSRF", "account_type": "asset",
            "csrf_token": "not-the-real-token",
        })
        assert "err=" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM accounts WHERE code = '9992'")
        assert cur.fetchone() is None


def test_post_with_valid_csrf_token_succeeds(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        with conn.cursor() as cur:
            cur.execute(
                "SELECT csrf_token FROM sessions WHERE token = %s",
                (c.cookies["libro_session"],))
            csrf_token = cur.fetchone()["csrf_token"]

        r = c.post("/accounts", data={
            "code": "9993", "name": "Valid CSRF", "account_type": "asset",
            "csrf_token": csrf_token,
        })
        assert r.status_code == 303
        assert "ok=" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM accounts WHERE code = '9993'")
        assert cur.fetchone() is not None


def test_logout_revokes_session(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        session_token = c.cookies["libro_session"]

        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s", (session_token,))
            csrf_token = cur.fetchone()["csrf_token"]

        c.post("/logout", data={"csrf_token": csrf_token})

        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM sessions WHERE token = %s", (session_token,))
            assert cur.fetchone() is None

        r = c.get("/")
        assert r.status_code == 303
        assert r.headers["location"] == "/login"

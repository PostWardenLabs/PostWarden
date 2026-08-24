"""Exercises the app-level auth: login, session/CSRF enforcement, logout.

Unlike test_invariants.py, this drives the actual FastAPI app (TestClient),
since these are things only the app layer enforces — the schema just holds
the users/sessions rows it checks against.
"""
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from conftest import mk_account, mk_user

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


def test_quick_create_payee_gets_or_creates_and_reactivates(conn):
    # Powers the "+ Create <name>" row in the payee combobox on New entry —
    # needs to (a) hand back a real id so the form has something to submit,
    # (b) not duplicate a payee that already exists under that exact name,
    # and (c) reactivate one the user had deactivated, since typing its
    # name here is exactly them signalling they want to use it again.
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

        r1 = c.post("/payees/quick-create",
                     data={"name": "Whole Foods", "csrf_token": csrf_token})
        assert r1.status_code == 200
        first = r1.json()
        assert first["ok"] is True
        assert first["name"] == "Whole Foods"

        with conn.cursor() as cur:
            cur.execute("UPDATE payees SET is_active = FALSE WHERE id = %s", (first["id"],))
        conn.commit()

        r2 = c.post("/payees/quick-create",
                     data={"name": "Whole Foods", "csrf_token": csrf_token})
        second = r2.json()
        assert second["id"] == first["id"]  # same row, not a duplicate

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n, bool_and(is_active) AS active "
                     "FROM payees WHERE name = 'Whole Foods'")
        row = cur.fetchone()
        assert row["n"] == 1
        assert row["active"] is True


def test_scheduled_entry_materializes_and_posts(conn):
    # End-to-end through the actual routes: create a schedule due today,
    # let the auth middleware's lazy materialize_due_schedules() pick it up
    # on the next request, then approve it — same path a real user takes,
    # just without the browser.
    with conn.cursor() as cur:
        user = mk_user(cur)
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
    conn.commit()

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute(
                "SELECT csrf_token FROM sessions WHERE token = %s",
                (c.cookies["libro_session"],))
            csrf_token = cur.fetchone()["csrf_token"]

        r = c.post("/scheduled", data={
            "csrf_token": csrf_token,
            "interval_count": "1", "interval_unit": "month",
            "next_date": date.today().isoformat(),
            "scenario_id": str(actual_id),
            "description": "Test schedule",
            "account": [acct1["code"], acct2["code"]],
            "debit": ["50", ""],
            "credit": ["", "50"],
            "memo": ["", ""],
        })
        assert r.status_code == 303
        assert "ok=" in r.headers["location"]

        # The auth middleware runs materialize_due_schedules() on every
        # request — this GET is what actually triggers it.
        assert c.get("/scheduled").status_code == 200

    with conn.cursor() as cur:
        cur.execute(
            """SELECT e.id, e.promoted_entry_id FROM journal_entries e
                 JOIN scenarios s ON s.id = e.scenario_id
                WHERE s.code = 'STAGING' AND e.description = 'Test schedule'""")
        staged = cur.fetchone()
        assert staged is not None
        assert staged["promoted_entry_id"] is None
        cur.execute("SELECT next_date FROM scheduled_entries WHERE description = 'Test schedule'")
        assert cur.fetchone()["next_date"] > date.today()  # advanced past today

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute(
                "SELECT csrf_token FROM sessions WHERE token = %s",
                (c.cookies["libro_session"],))
            csrf_token = cur.fetchone()["csrf_token"]

        r2 = c.post("/scheduled/post",
                    data={"entry_id": str(staged["id"]), "csrf_token": csrf_token})
        assert r2.status_code == 303
        assert "ok=" in r2.headers["location"]

        # Re-posting the same (now-promoted) staging entry must fail, not
        # silently duplicate the real entry.
        r3 = c.post("/scheduled/post",
                    data={"entry_id": str(staged["id"]), "csrf_token": csrf_token})
        assert "already+posted" in r3.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT promoted_entry_id FROM journal_entries WHERE id = %s",
                    (staged["id"],))
        promoted_id = cur.fetchone()["promoted_entry_id"]
        assert promoted_id is not None
        cur.execute(
            "SELECT scenario_id, description FROM journal_entries WHERE id = %s",
            (promoted_id,))
        real = cur.fetchone()
        assert real["scenario_id"] == actual_id
        assert real["description"] == "Test schedule"
        cur.execute("SELECT COUNT(*) AS n FROM journal_lines WHERE entry_id = %s",
                    (promoted_id,))
        assert cur.fetchone()["n"] == 2


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

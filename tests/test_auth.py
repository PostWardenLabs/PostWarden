"""Exercises the app-level auth: login, session/CSRF enforcement, logout.

Unlike test_invariants.py, this drives the actual FastAPI app (TestClient),
since these are things only the app layer enforces — the schema just holds
the users/sessions rows it checks against.
"""
import json
import re
from datetime import date

from fastapi.testclient import TestClient

from app.main import app
from conftest import mk_account, mk_entry, mk_line, mk_scenario, mk_user

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


def test_create_template_requires_balance_and_saves_lines(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute(
                "SELECT csrf_token FROM sessions WHERE token = %s",
                (c.cookies["libro_session"],))
            csrf_token = cur.fetchone()["csrf_token"]

        # Unbalanced — rejected, nothing saved.
        r1 = c.post("/templates", data={
            "csrf_token": csrf_token, "name": "Bad template", "description": "x",
            "account": [acct1["code"]], "debit": ["10"], "credit": [""], "memo": [""],
        })
        assert "err=" in r1.headers["location"]

        # Balanced — saved, with tags and both lines.
        r2 = c.post("/templates", data={
            "csrf_token": csrf_token, "name": "Good template", "description": "Rent",
            "tags": "housing,monthly",
            "account": [acct1["code"], acct2["code"]],
            "debit": ["25", ""], "credit": ["", "25"], "memo": ["", ""],
        })
        assert r2.status_code == 303
        assert "ok=" in r2.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM entry_templates WHERE name = 'Bad template'")
        assert cur.fetchone() is None

        cur.execute("SELECT id FROM entry_templates WHERE name = 'Good template'")
        tid = cur.fetchone()["id"]
        cur.execute(
            "SELECT COUNT(*) AS n FROM entry_template_lines WHERE template_id = %s", (tid,))
        assert cur.fetchone()["n"] == 2
        cur.execute(
            """SELECT tg.name FROM entry_template_tags ett
               JOIN tags tg ON tg.id = ett.tag_id
              WHERE ett.template_id = %s ORDER BY tg.name""", (tid,))
        assert [r["name"] for r in cur.fetchall()] == ["housing", "monthly"]


def test_quick_create_account_inherits_parent_type_and_generates_code(conn):
    # Powers the "+" gap rows on /accounts (see accounts.js) — a child
    # inherits its parent's type and account_type is ignored even if sent
    # (the parent decides); a top-level account requires an explicit,
    # valid account_type since there's no parent to inherit from.
    with conn.cursor() as cur:
        user = mk_user(cur)
        parent = mk_account(cur, account_type="liability", postable=False)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute(
                "SELECT csrf_token FROM sessions WHERE token = %s",
                (c.cookies["libro_session"],))
            csrf_token = cur.fetchone()["csrf_token"]

        r1 = c.post("/accounts/quick-create", data={
            "csrf_token": csrf_token, "name": "New Card",
            "parent_id": str(parent["id"]), "account_type": "asset",
        })
        assert "ok=" in r1.headers["location"]

        r2 = c.post("/accounts/quick-create", data={
            "csrf_token": csrf_token, "name": "New Top Level",
            "parent_id": "", "account_type": "income",
        })
        assert "ok=" in r2.headers["location"]

        r3 = c.post("/accounts/quick-create", data={
            "csrf_token": csrf_token, "name": "No type given", "parent_id": "",
        })
        assert "err=" in r3.headers["location"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT account_type, parent_id, code FROM accounts WHERE name = 'New Card'")
        child = cur.fetchone()
        assert child["account_type"] == "liability"  # inherited, not "asset"
        assert child["parent_id"] == parent["id"]

        cur.execute(
            "SELECT account_type, parent_id, code FROM accounts WHERE name = 'New Top Level'")
        top = cur.fetchone()
        assert top["account_type"] == "income"
        assert top["parent_id"] is None
        assert top["code"].startswith("4")  # income prefix

        cur.execute("SELECT 1 FROM accounts WHERE name = 'No type given'")
        assert cur.fetchone() is None


def test_scenario_base_level_relaxes_posting_through_the_real_routes(conn):
    # End-to-end through the actual routes, not just the DB trigger: pick
    # "Subaccounts" (depth 2, seeded by seed.sql) as a new scenario's base
    # level, then post an entry straight to a depth-2 summary account.
    with conn.cursor() as cur:
        user = mk_user(cur)
        parent = mk_account(cur, postable=False)
        child = mk_account(cur, parent_id=parent["id"], postable=False)
        cur.execute("SELECT id FROM account_levels WHERE depth = 2")
        level2_id = cur.fetchone()["id"]
    conn.commit()

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute(
                "SELECT csrf_token FROM sessions WHERE token = %s",
                (c.cookies["libro_session"],))
            csrf_token = cur.fetchone()["csrf_token"]

        r1 = c.post("/scenarios", data={
            "csrf_token": csrf_token, "code": "COARSE1", "name": "Coarse test",
            "scenario_type": "budget", "base_level_id": str(level2_id),
        })
        assert "ok=" in r1.headers["location"]
        with conn.cursor() as cur:
            cur.execute("SELECT id, base_level_id FROM scenarios WHERE code = 'COARSE1'")
            scen = cur.fetchone()
            assert scen["base_level_id"] == level2_id

        r2 = c.post("/entries", data={
            "csrf_token": csrf_token, "entry_date": "2026-01-01",
            "scenario_id": str(scen["id"]), "description": "Post to summary account",
            "account": [child["code"]], "debit": ["10"], "credit": [""], "memo": [""],
        })
        assert "err=" not in r2.headers["location"]
        assert "ok=" in r2.headers["location"]

    with conn.cursor() as cur:
        cur.execute(
            """SELECT 1 FROM journal_lines l JOIN journal_entries e ON e.id = l.entry_id
               WHERE e.scenario_id = %s AND l.account_id = %s""",
            (scen["id"], child["id"]))
        assert cur.fetchone() is not None


def test_new_entry_page_embeds_per_scenario_account_lists(conn):
    # The account picker used to be one static list shared by every
    # scenario (a known simplification); it's now scenario-aware — New
    # entry embeds a {scenario_id: [account, ...]} blob and app.js
    # re-filters the grid's <select>s to it when the Scenario field
    # changes. Confirms the blob itself is correct at the source: a
    # summary account only appears under scenarios whose base_level
    # actually includes it.
    with conn.cursor() as cur:
        user = mk_user(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
        cur.execute("SELECT id FROM account_levels WHERE depth = 1")
        level1_id = cur.fetchone()["id"]
        parent = mk_account(cur, postable=False)  # depth 1
        coarse = mk_scenario(cur, base_level_id=level1_id)
    conn.commit()

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/entries/new")
        assert r.status_code == 200
        blob = json.loads(
            re.search(
                r'id="accounts-by-scenario-data">(.*?)</script>', r.text, re.S
            ).group(1))
        actual_codes = {a["code"] for a in blob[str(actual_id)]}
        coarse_codes = {a["code"] for a in blob[str(coarse["id"])]}
        assert parent["code"] not in actual_codes  # ACTUAL: leaves only
        assert parent["code"] in coarse_codes      # coarse scenario: also this


def test_account_levels_crud(conn):
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

        r1 = c.post("/account-levels", data={
            "csrf_token": csrf_token, "name": "Test Level", "depth": "97",
        })
        assert "ok=" in r1.headers["location"]
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM account_levels WHERE depth = 97")
            level_id = cur.fetchone()["id"]

        r2 = c.post(f"/account-levels/{level_id}/rename",
                    data={"csrf_token": csrf_token, "name": "Renamed Level"})
        assert "ok=" in r2.headers["location"]

        r3 = c.post(f"/account-levels/{level_id}/delete",
                    data={"csrf_token": csrf_token})
        assert "ok=" in r3.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT name FROM account_levels WHERE depth = 97")
        assert cur.fetchone() is None  # deleted


def test_variance_page_rolls_up_a_coarse_scenario_against_a_fine_one(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
        cur.execute("SELECT id FROM account_levels WHERE depth = 1")
        level1_id = cur.fetchone()["id"]
        parent = mk_account(cur, postable=False)                          # depth 1
        leaf1 = mk_account(cur, parent_id=parent["id"])                   # depth 2
        leaf2 = mk_account(cur, parent_id=parent["id"])                   # depth 2
        budget = mk_scenario(cur, base_level_id=level1_id, enforce_balance=False)

        # Actual: posted at the fine (leaf) level, split across two accounts
        # (plus a balancing counter-line — ACTUAL enforces balance).
        counter = mk_account(cur)
        eid = mk_entry(cur, actual_id)
        mk_line(cur, eid, leaf1["id"], 40, line_no=1)
        mk_line(cur, eid, leaf2["id"], 60, line_no=2)
        mk_line(cur, eid, counter["id"], -100, line_no=3)
        # Budget: posted straight to the coarse parent (single-sided OK).
        eid2 = mk_entry(cur, budget["id"])
        mk_line(cur, eid2, parent["id"], 90)
    conn.commit()

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/variance?baseline=ACTUAL&compare={budget['code']}")
        assert r.status_code == 200
        assert parent["code"] in r.text
        # money-format.js's data-value carries the exact unformatted
        # number (no thousands separator), so these can't collide with
        # unrelated pre-existing amounts elsewhere on a shared test DB
        # the way a bare "100.00" substring search could.
        assert 'data-value="100.00"' in r.text  # actual: 40 + 60 rolled into the parent
        assert 'data-value="90.00"' in r.text   # budget: posted straight to the parent
        assert 'data-value="-10.00"' in r.text  # variance: 90 - 100


def test_accounts_page_filters_to_selected_level(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        parent = mk_account(cur, postable=False)
        child = mk_account(cur, parent_id=parent["id"])
        cur.execute("SELECT id FROM account_levels WHERE depth = 1")
        level1_id = cur.fetchone()["id"]
    conn.commit()

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        # Each account's own toggle-active form action is unique and only
        # ever rendered inside the accounts *table* — unlike the code/name,
        # which can also legitimately appear in the (deliberately
        # unfiltered) "New account" Parent dropdown.
        child_marker = f"/accounts/{child['id']}/toggle-active"

        r_all = c.get("/accounts")
        assert parent["code"] in r_all.text
        assert child_marker in r_all.text  # unfiltered: both show

        r_level1 = c.get(f"/accounts?level_id={level1_id}")
        assert parent["code"] in r_level1.text
        assert child_marker not in r_level1.text  # filtered to depth 1 only


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

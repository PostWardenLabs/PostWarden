"""Exercises the app-level auth: login, session/CSRF enforcement, logout.

Unlike test_invariants.py, this drives the actual FastAPI app (TestClient),
since these are things only the app layer enforces — the schema just holds
the users/sessions rows it checks against.
"""
import json
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, unquote, urlparse

from fastapi.testclient import TestClient

from app.main import app, dateformat, templates
from conftest import (mk_account, mk_budget_line, mk_entry, mk_line, mk_payee,
                     mk_scenario, mk_tag, mk_user)

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
        assert "postwarden_session" not in c.cookies


def test_login_correct_succeeds_and_grants_access(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        r = c.post("/login", data={"username": user["username"], "password": user["password"]})
        assert r.status_code == 303
        assert r.headers["location"] == "/"
        assert "postwarden_session" in c.cookies

        r = c.get("/")
        assert r.status_code == 200
        assert '<a class="wordmark" href="/">Dashboard<span class="wordmark-brand"> · PostWarden</span></a>' in r.text


def test_remember_me_controls_cookie_lifetime(conn):
    """Unchecked, the cookie carries no Max-Age at all — a plain session
    cookie the browser drops on its own — regardless of the *session*
    row behind it still being good for the full SESSION_TTL either way
    (see auth.create_session/login_submit)."""
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        r = c.post("/login", data={"username": user["username"], "password": user["password"]})
        assert "max-age" not in r.headers["set-cookie"].lower()

    with TestClient(app, **client_kwargs) as c:
        r = c.post("/login", data={"username": user["username"], "password": user["password"],
                                   "remember": "on"})
        assert "max-age=2592000" in r.headers["set-cookie"].lower()


def test_inactive_user_cannot_log_in(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        cur.execute("UPDATE users SET is_active = FALSE WHERE id = %s", (user["id"],))
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        r = c.post("/login", data={"username": user["username"], "password": user["password"]})
        assert r.headers["location"].startswith("/login?err=")
        assert "postwarden_session" not in c.cookies


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
                (c.cookies["postwarden_session"],))
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
                (c.cookies["postwarden_session"],))
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
                (c.cookies["postwarden_session"],))
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
                (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]

        r2 = c.post("/staging/approve",
                    data={"entry_id": str(staged["id"]), "csrf_token": csrf_token})
        assert r2.status_code == 303
        assert "ok=" in r2.headers["location"]

        # Re-approving the same (now-promoted) staging entry must fail, not
        # silently duplicate the real entry.
        r3 = c.post("/staging/approve",
                    data={"entry_id": str(staged["id"]), "csrf_token": csrf_token})
        assert "already+approved" in r3.headers["location"]

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


def test_staging_excluded_from_new_entry_and_scheduled_target_pickers(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        cur.execute("SELECT id FROM scenarios WHERE is_staging")
        staging_id = cur.fetchone()["id"]
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/entries?new=1")
        select_html = re.search(
            r'<select name="scenario_id" id="scenario">.*?</select>', r.text, re.S).group(0)
        assert f'value="{staging_id}"' not in select_html

        r = c.get("/scheduled")
        select_html = re.search(
            r'<select name="scenario_id" id="scenario">.*?</select>', r.text, re.S).group(0)
        assert f'value="{staging_id}"' not in select_html


def test_staging_page_lists_pending_entries_and_approves_them(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
        cur.execute("SELECT id FROM scenarios WHERE is_staging")
        staging_id = cur.fetchone()["id"]
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
        cur.execute(
            """INSERT INTO scheduled_entries
                   (description, target_scenario_id, interval_unit, next_date)
               VALUES ('Staged via test', %s, 'month', CURRENT_DATE) RETURNING id""",
            (actual_id,))
        sched_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO journal_entries
                   (scenario_id, entry_date, description, scheduled_entry_id)
               VALUES (%s, CURRENT_DATE, 'Staged via test', %s) RETURNING id""",
            (staging_id, sched_id))
        eid = cur.fetchone()["id"]
        mk_line(cur, eid, acct1["id"], 40, line_no=1)
        mk_line(cur, eid, acct2["id"], -40, line_no=2)
    conn.commit()

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/staging")
        assert r.status_code == 200
        assert "Staged via test" in r.text
        assert f'value="{eid}"' in r.text
        assert 'id="select-all"' in r.text
        assert 'id="approve-btn" disabled' in r.text
        # Edit is an inline panel now (staging-inline-edit.js), not a link
        # to a separate page — a button carrying the entry's id, plus the
        # one shared panel it relocates into place, parked hidden. Styled
        # like a real button (.quiet, same as Approve/Reject's own look),
        # not the plain-text .quiet-link treatment.
        assert f'class="quiet staging-edit-btn" data-entry-id="{eid}"' in r.text
        assert f'href="/staging/{eid}/edit"' not in r.text
        assert 'id="staging-edit-panel" hidden' in r.text

        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r2 = c.post("/staging/approve", data={"entry_id": str(eid), "csrf_token": csrf_token})
        assert r2.status_code == 303
        assert "ok=" in r2.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT promoted_entry_id FROM journal_entries WHERE id = %s", (eid,))
        promoted_id = cur.fetchone()["promoted_entry_id"]
        assert promoted_id is not None
        cur.execute("SELECT scenario_id FROM journal_entries WHERE id = %s", (promoted_id,))
        assert cur.fetchone()["scenario_id"] == actual_id


def _mk_staged_entry(cur, description="Staged via test", target_scenario_id=None, amount=40):
    """A pending Staging entry, same shape test_staging_page_lists_
    pending_entries_and_approves_them builds by hand — factored out
    since both the edit and reject tests below need one too. Defaults to
    targeting ACTUAL and a 40/-40 line pair; the filter tests override
    target_scenario_id/amount to get entries that actually differ."""
    if target_scenario_id is None:
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        target_scenario_id = cur.fetchone()["id"]
    cur.execute("SELECT id FROM scenarios WHERE is_staging")
    staging_id = cur.fetchone()["id"]
    acct1 = mk_account(cur)
    acct2 = mk_account(cur)
    cur.execute(
        """INSERT INTO scheduled_entries
               (description, target_scenario_id, interval_unit, next_date)
           VALUES (%s, %s, 'month', CURRENT_DATE) RETURNING id""",
        (description, target_scenario_id))
    sched_id = cur.fetchone()["id"]
    cur.execute(
        """INSERT INTO journal_entries
               (scenario_id, entry_date, description, scheduled_entry_id)
           VALUES (%s, CURRENT_DATE, %s, %s) RETURNING id""",
        (staging_id, description, sched_id))
    eid = cur.fetchone()["id"]
    mk_line(cur, eid, acct1["id"], amount, line_no=1)
    mk_line(cur, eid, acct2["id"], -amount, line_no=2)
    return eid, acct1, acct2


def test_staging_edit_data_returns_the_entry_and_its_lines(conn):
    # GET /staging/{id}/edit is a JSON data endpoint now, not a page —
    # staging-inline-edit.js fetches it to fill in the shared edit panel
    # in place, rather than navigating to a separate screen.
    with conn.cursor() as cur:
        user = mk_user(cur)
        eid, acct1, acct2 = _mk_staged_entry(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/staging/{eid}/edit")
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["entry"]["description"] == "Staged via test"
        codes = [ln["code"] for ln in data["lines"]]
        assert acct1["code"] in codes
        assert acct2["code"] in codes
        assert data["lines"][0]["debit"] == "40.00"


def test_staging_edit_replaces_the_lines_and_updates_the_header(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        eid, acct1, acct2 = _mk_staged_entry(cur)
        acct3 = mk_account(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post(f"/staging/{eid}/edit", data={
            "csrf_token": csrf_token, "entry_date": "2026-01-02",
            "description": "Edited description", "reference": "REF1",
            "account": [acct1["code"], acct3["code"]],
            "debit": ["55", ""], "credit": ["", "55"], "memo": ["fixed", ""],
        })
        assert r.status_code == 303
        assert "ok=" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute(
            "SELECT description, reference, entry_date FROM journal_entries WHERE id = %s",
            (eid,))
        row = cur.fetchone()
        assert row["description"] == "Edited description"
        assert row["reference"] == "REF1"
        assert str(row["entry_date"]) == "2026-01-02"

        cur.execute(
            """SELECT a.code, l.debit, l.credit, l.memo FROM journal_lines l
                JOIN accounts a ON a.id = l.account_id
               WHERE l.entry_id = %s ORDER BY l.line_no""",
            (eid,))
        lines = cur.fetchall()
        assert [ln["code"] for ln in lines] == [acct1["code"], acct3["code"]]
        assert str(lines[0]["debit"]) == "55.00"
        assert lines[0]["memo"] == "fixed"
        # acct2 from the original pair is gone — a real replace, not a merge.
        assert acct2["code"] not in [ln["code"] for ln in lines]


def test_staging_edit_rejects_an_already_approved_entry(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        eid, _, _ = _mk_staged_entry(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
        real_id = mk_entry(cur, actual_id, "Already approved")
        real_acct1, real_acct2 = mk_account(cur), mk_account(cur)
        mk_line(cur, real_id, real_acct1["id"], 10, line_no=1)
        mk_line(cur, real_id, real_acct2["id"], -10, line_no=2)
        cur.execute(
            "UPDATE journal_entries SET promoted_entry_id = %s WHERE id = %s",
            (real_id, eid))
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.get(f"/staging/{eid}/edit")
        assert r.status_code == 400
        assert r.json()["ok"] is False

        r2 = c.post(f"/staging/{eid}/edit", data={
            "csrf_token": csrf_token, "entry_date": "2026-01-02",
            "description": "Should not apply",
            "account": [], "debit": [], "credit": [], "memo": [],
        })
        assert "err=" in r2.headers["location"]
    with conn.cursor() as cur:
        cur.execute("SELECT description FROM journal_entries WHERE id = %s", (eid,))
        assert cur.fetchone()["description"] != "Should not apply"


def test_staging_reject_deletes_the_entry_and_its_lines(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        eid, _, _ = _mk_staged_entry(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post(f"/staging/{eid}/reject", data={"csrf_token": csrf_token})
        assert r.status_code == 303
        assert "ok=" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM journal_entries WHERE id = %s", (eid,))
        assert cur.fetchone()["n"] == 0
        cur.execute("SELECT COUNT(*) AS n FROM journal_lines WHERE entry_id = %s", (eid,))
        assert cur.fetchone()["n"] == 0


def test_staging_reject_refuses_an_already_approved_entry(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        eid, _, _ = _mk_staged_entry(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
        real_id = mk_entry(cur, actual_id, "Already approved")
        real_acct1, real_acct2 = mk_account(cur), mk_account(cur)
        mk_line(cur, real_id, real_acct1["id"], 10, line_no=1)
        mk_line(cur, real_id, real_acct2["id"], -10, line_no=2)
        cur.execute(
            "UPDATE journal_entries SET promoted_entry_id = %s WHERE id = %s",
            (real_id, eid))
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post(f"/staging/{eid}/reject", data={"csrf_token": csrf_token})
        assert "err=" in r.headers["location"]
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM journal_entries WHERE id = %s", (eid,))
        assert cur.fetchone()["n"] == 1  # still there — reject was refused


def test_staging_bulk_reject_deletes_every_checked_entry(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        eid1, _, _ = _mk_staged_entry(cur, description="Bulk reject me 1")
        eid2, _, _ = _mk_staged_entry(cur, description="Bulk reject me 2")
        eid3, _, _ = _mk_staged_entry(cur, description="Leave me alone")
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/staging")
        # The top-of-page bulk Reject sits next to Approve, both disabled
        # until something's checked, and the old second "Approve entries"
        # button at the bottom of the list is gone.
        assert 'id="approve-btn" disabled' in r.text
        assert 'id="reject-btn" disabled' in r.text
        assert "approve-btn-bottom" not in r.text

        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r2 = c.post("/staging/reject", data={
            "entry_id": [str(eid1), str(eid2)], "csrf_token": csrf_token,
        })
        assert r2.status_code == 303
        assert "ok=" in r2.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM journal_entries WHERE id = ANY(%s)", ([eid1, eid2],))
        assert cur.fetchall() == []
        cur.execute("SELECT id FROM journal_entries WHERE id = %s", (eid3,))
        assert cur.fetchone()["id"] == eid3  # untouched


def test_staging_bulk_reject_requires_at_least_one_entry(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        _mk_staged_entry(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post("/staging/reject", data={"csrf_token": csrf_token})
        assert "err=" in r.headers["location"]


def test_staging_page_filters_by_target_scenario_and_amount(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        other = mk_scenario(cur, scenario_type="forecast")
        eid_actual, _, _ = _mk_staged_entry(cur, description="Headed for ACTUAL", amount=10)
        eid_other, _, _ = _mk_staged_entry(
            cur, description="Headed elsewhere", target_scenario_id=other["id"], amount=999)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        r = c.get(f"/staging?target_scenario={other['code']}")
        assert "Headed elsewhere" in r.text
        assert "Headed for ACTUAL" not in r.text

        r = c.get("/staging?amount_op=gte&amount_value=500")
        assert "Headed elsewhere" in r.text
        assert "Headed for ACTUAL" not in r.text

        # Both still show with nothing filtered.
        r = c.get("/staging")
        assert "Headed elsewhere" in r.text and "Headed for ACTUAL" in r.text


def test_dashboard_links_to_staging_when_entries_pending(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
        cur.execute("SELECT id FROM scenarios WHERE is_staging")
        staging_id = cur.fetchone()["id"]
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
        cur.execute(
            """INSERT INTO scheduled_entries
                   (description, target_scenario_id, interval_unit, next_date)
               VALUES ('Dashboard staged', %s, 'month', CURRENT_DATE) RETURNING id""",
            (actual_id,))
        sched_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO journal_entries
                   (scenario_id, entry_date, description, scheduled_entry_id)
               VALUES (%s, CURRENT_DATE, 'Dashboard staged', %s) RETURNING id""",
            (staging_id, sched_id))
        eid = cur.fetchone()["id"]
        mk_line(cur, eid, acct1["id"], 15, line_no=1)
        mk_line(cur, eid, acct2["id"], -15, line_no=2)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/")
        assert r.status_code == 200
        assert 'href="/staging"' in r.text
        assert "waiting in Staging for your approval" in r.text


def test_import_csv_stages_entries_and_approves_into_target(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        target = mk_scenario(cur, enforce_balance=False)
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
    conn.commit()
    csv_text = (
        "Entry #,Date,Scenario,Description,Reference,Payee,Account code,Account name,Debit,Credit,Memo\n"
        f"1,2026-08-01,ACTUAL,Imported entry,REF1,Acme,{acct1['code']},Acct 1,40,,\n"
        f"1,2026-08-01,ACTUAL,Imported entry,REF1,Acme,{acct2['code']},Acct 2,,40,\n"
    )
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]

        r = c.post("/import",
                   data={"csrf_token": csrf_token, "target_scenario_id": str(target["id"])},
                   files={"file": ("bank.csv", csv_text, "text/csv")})
        assert r.status_code == 303
        assert "Staged+1+entry" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute(
            """SELECT e.id, e.promoted_entry_id, p.name AS payee_name
                 FROM journal_entries e
                 JOIN scenarios s ON s.id = e.scenario_id
                 LEFT JOIN payees p ON p.id = e.payee_id
                WHERE s.is_staging AND e.description = 'Imported entry'""")
        staged = cur.fetchone()
        assert staged is not None
        assert staged["payee_name"] == "Acme"
        assert staged["promoted_entry_id"] is None
        cur.execute("SELECT COUNT(*) AS n FROM journal_lines WHERE entry_id = %s", (staged["id"],))
        assert cur.fetchone()["n"] == 2

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post("/staging/approve",
                   data={"entry_id": str(staged["id"]), "csrf_token": csrf_token})
        assert "ok=" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT promoted_entry_id FROM journal_entries WHERE id = %s", (staged["id"],))
        promoted_id = cur.fetchone()["promoted_entry_id"]
        assert promoted_id is not None
        cur.execute("SELECT scenario_id FROM journal_entries WHERE id = %s", (promoted_id,))
        assert cur.fetchone()["scenario_id"] == target["id"]


def test_import_csv_reports_bad_rows_and_still_stages_the_valid_ones(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        target = mk_scenario(cur, enforce_balance=False)
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
    conn.commit()
    csv_text = (
        "Entry #,Date,Description,Account code,Debit,Credit\n"
        # Entry 1: valid, should stage.
        f"1,2026-08-01,Good entry,{acct1['code']},40,\n"
        f"1,2026-08-01,Good entry,{acct2['code']},,40\n"
        # Entry 2: unbalanced — should be reported, not staged.
        f"2,2026-08-02,Bad entry,{acct1['code']},50,\n"
        f"2,2026-08-02,Bad entry,{acct2['code']},,30\n"
        # Entry 3: unknown account code.
        "3,2026-08-03,Unknown account,NOPE999,10,\n"
    )
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post("/import",
                   data={"csrf_token": csrf_token, "target_scenario_id": str(target["id"])},
                   files={"file": ("bank.csv", csv_text, "text/csv")})
        assert r.status_code == 303
        loc = r.headers["location"]
        assert "ok=" in loc and "err=" in loc

    with conn.cursor() as cur:
        cur.execute(
            """SELECT description FROM journal_entries e
                 JOIN scenarios s ON s.id = e.scenario_id
                WHERE s.is_staging AND e.description IN ('Good entry', 'Bad entry', 'Unknown account')""")
        staged_descriptions = {r["description"] for r in cur.fetchall()}
        assert staged_descriptions == {"Good entry"}


def test_import_csv_rejects_a_file_missing_required_columns(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        target = mk_scenario(cur)
    conn.commit()
    csv_text = "Date,Description\n2026-08-01,Nope\n"
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post("/import",
                   data={"csrf_token": csrf_token, "target_scenario_id": str(target["id"])},
                   files={"file": ("bad.csv", csv_text, "text/csv")})
        assert r.status_code == 303
        assert "err=" in r.headers["location"]
        assert "Missing+required+column" in r.headers["location"]


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
                (c.cookies["postwarden_session"],))
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
                (c.cookies["postwarden_session"],))
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
                (c.cookies["postwarden_session"],))
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


def test_entries_rejects_a_non_numeric_debit_with_a_friendly_message(conn):
    # A stray non-numeric string in Debit/Credit used to reach float()
    # unguarded, surfacing Python's own "could not convert string to
    # float: '...'" straight to the user. _parse_lines now catches that
    # and raises its own message instead.
    with conn.cursor() as cur:
        user = mk_user(cur)
        acct = mk_account(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
    conn.commit()

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute(
                "SELECT csrf_token FROM sessions WHERE token = %s",
                (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]

        r = c.post("/entries", data={
            "csrf_token": csrf_token, "entry_date": "2026-01-01",
            "scenario_id": str(actual_id), "description": "Bad amount",
            "account": [acct["code"]], "debit": ["abc"], "credit": [""],
            "memo": [""],
        })
        assert "err=" in r.headers["location"]
        assert "could+not+convert" not in r.headers["location"]
        assert "debit+and+credit+must+be+numbers" in r.headers["location"]


def test_entries_new_redirects_to_journal_with_panel_open(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/entries/new")
        assert r.status_code == 303
        assert r.headers["location"] == "/entries?new=1"


def test_journal_page_embeds_per_scenario_account_lists_for_new_entry_panel(conn):
    # The account picker used to be one static list shared by every
    # scenario (a known simplification); it's now scenario-aware — the
    # Journal's "+ New entry" panel embeds a {scenario_id: [account, ...]}
    # blob and app.js re-filters the grid's <select>s to it when the
    # Scenario field changes. Confirms the blob itself is correct at the
    # source: a summary account only appears under scenarios whose
    # base_level actually includes it.
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
        r = c.get("/entries?new=1")
        assert r.status_code == 200
        assert 'id="new-entry-panel" open' in r.text
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
                (c.cookies["postwarden_session"],))
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
        assert 'data-value="10.00"' in r.text   # variance: baseline(100) - compare(90)
        assert "10.0%" in r.text                # % variance: (100 - 90) / |100| * 100


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
        session_token = c.cookies["postwarden_session"]

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


def test_journal_new_entry_panel_closed_by_default(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/entries")
        assert r.status_code == 200
        assert 'id="new-entry-panel" >' in r.text  # present, but no "open" attribute
        assert 'id="new-entry-panel" open' not in r.text


def test_entries_page_paginates_older_entries_behind_a_link(conn):
    from app.main import ENTRIES_PAGE_SIZE
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)  # single-sided: one line per entry
        acct = mk_account(cur)
        for i in range(ENTRIES_PAGE_SIZE + 1):
            eid = mk_entry(cur, scen["id"], description=f"Entry {i}")
            mk_line(cur, eid, acct["id"], 10)
    conn.commit()

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        r1 = c.get("/entries")
        assert r1.status_code == 200
        assert f"Entry {ENTRIES_PAGE_SIZE}" in r1.text  # most recent: on page 1
        assert "Entry 0" not in r1.text                 # oldest: pushed to page 2
        assert "page=2" in r1.text                       # Older link present
        assert "page=0" not in r1.text                   # no Newer link on page 1

        r2 = c.get("/entries?page=2")
        assert r2.status_code == 200
        assert "Entry 0" in r2.text
        assert f"Entry {ENTRIES_PAGE_SIZE}" not in r2.text
        assert "page=1" in r2.text     # Newer link back to page 1
        assert "page=3" not in r2.text  # no further Older link


def test_entries_export_csv_respects_the_scenario_filter(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen_a = mk_scenario(cur, enforce_balance=False)
        scen_b = mk_scenario(cur, enforce_balance=False)
        acct_a = mk_account(cur)
        acct_b = mk_account(cur)
        mk_line(cur, mk_entry(cur, scen_a["id"]), acct_a["id"], 12.50)
        mk_line(cur, mk_entry(cur, scen_b["id"]), acct_b["id"], 34.00)
    conn.commit()

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/entries/export.csv?scenario={scen_a['code']}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert acct_a["code"] in r.text
        assert acct_b["code"] not in r.text


def test_trial_balance_export_csv(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/export/trial-balance.csv?scenario=ACTUAL")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        # Leading ﻿ is a deliberate UTF-8 BOM so Excel doesn't mangle
        # accented characters — strip it before comparing the header row.
        assert r.text.lstrip("﻿").splitlines()[0] == "Code,Account,Path,Debit,Credit"


def test_variance_export_csv(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        budget = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        mk_line(cur, mk_entry(cur, budget["id"]), acct["id"], 77.00)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/export/variance.csv?baseline=ACTUAL&compare={budget['code']}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/csv")
        assert acct["code"] in r.text
        assert "77.0" in r.text


def test_trial_balance_moved_off_root(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/trial-balance")
        assert r.status_code == 200
        assert '<a class="wordmark" href="/">Trial Balance<span class="wordmark-brand"> · PostWarden</span></a>' in r.text


def _mk_balanced_book(conn):
    """Asset 500 <- Equity 500 (opening), Asset +200 <- Income 200,
    Expense 50 <- Asset -50. Everything dated today (mk_entry always
    uses CURRENT_DATE) — used by the dashboard/income-statement/
    balance-sheet tests below to check the arithmetic, not date exclusion
    (that's covered separately for the income statement)."""
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
        asset = mk_account(cur, account_type="asset")
        equity = mk_account(cur, account_type="equity")
        income = mk_account(cur, account_type="income")
        expense = mk_account(cur, account_type="expense")

        e1 = mk_entry(cur, actual_id, "Opening")
        mk_line(cur, e1, asset["id"], 500, line_no=1)
        mk_line(cur, e1, equity["id"], -500, line_no=2)

        e2 = mk_entry(cur, actual_id, "Income")
        mk_line(cur, e2, asset["id"], 200, line_no=1)
        mk_line(cur, e2, income["id"], -200, line_no=2)

        e3 = mk_entry(cur, actual_id, "Expense")
        mk_line(cur, e3, expense["id"], 50, line_no=1)
        mk_line(cur, e3, asset["id"], -50, line_no=2)
    conn.commit()
    return {"asset": asset, "equity": equity, "income": income, "expense": expense}


def _account_row_value(html: str, code: str) -> str:
    """The money-fmt data-value from a specific account's own table row.
    Anchored on that account's code rather than a bare data-value search:
    the test database is shared across the *whole* pytest run (see
    conftest.py — one disposable DB per run, not per test), so ACTUAL
    already carries postings from every other test that touched it by
    the time this one runs. A page-wide total is not isolated; a single
    account's own row still is, since every test uses a fresh randomly-
    coded account no other test ever posts to."""
    m = re.search(rf'<td class="mono dim">{code}</td>.*?data-value="(-?[\d.]+)"', html, re.S)
    assert m, f"no row found for account {code}"
    return m.group(1)


def test_dashboard_computes_net_worth_and_month_to_date(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        # Same contamination problem as the trial balance's totals — the
        # dashboard's stat tiles are aggregates over the whole ACTUAL
        # scenario, so check the *delta* a known-size book adds rather
        # than an absolute figure.
        before = [float(v) for v in re.findall(r'data-value="(-?[\d.]+)"', c.get("/").text)[:4]]
        _mk_balanced_book(conn)
        after = [float(v) for v in re.findall(r'data-value="(-?[\d.]+)"', c.get("/").text)[:4]]
        deltas = [round(a - b, 2) for a, b in zip(after, before)]
        assert deltas == [650.00, 200.00, 50.00, 150.00]  # net worth, income, expenses, net


def test_income_statement_date_range_excludes_out_of_window_activity(conn):
    accts = _mk_balanced_book(conn)
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        # A window entirely before today excludes all of it.
        r_past = c.get("/income-statement?date_from=2000-01-01&date_to=2000-01-31")
        assert r_past.status_code == 200
        assert accts["income"]["code"] not in r_past.text
        assert "No income or expense activity" in r_past.text

        # A window covering today (the only date mk_entry ever uses) includes it.
        today = date.today().isoformat()
        r_now = c.get(f"/income-statement?date_from={today}&date_to={today}")
        assert _account_row_value(r_now.text, accts["income"]["code"]) == "200.00"
        assert _account_row_value(r_now.text, accts["expense"]["code"]) == "50.00"


def test_balance_sheet_balances_via_current_earnings(conn):
    accts = _mk_balanced_book(conn)
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/balance-sheet")
        assert r.status_code == 200
        # The books balance regardless of how much other tests have
        # posted to ACTUAL in this shared run — that's the actual
        # invariant "Current earnings" exists to preserve without ever
        # posting a physical period-closing entry.
        assert "out-of-balance" not in r.text
        assert _account_row_value(r.text, accts["asset"]["code"]) == "650.00"
        assert _account_row_value(r.text, accts["equity"]["code"]) == "500.00"


def test_income_statement_splits_multiple_top_level_expense_groups(conn):
    # A user with a second top-level expense account (e.g. "6000 Other
    # expenses" next to the original "5000 Expenses") should see two
    # sections, each with its own subtotal and its own running "Net
    # income" line — not one merged Expenses bucket.
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        income = mk_account(cur, account_type="income", code="590100")
        expense_a = mk_account(cur, account_type="expense", code="591100")
        expense_b = mk_account(cur, account_type="expense", code="592100")
        mk_line(cur, mk_entry(cur, scen["id"]), income["id"], -300)
        mk_line(cur, mk_entry(cur, scen["id"]), expense_a["id"], 100)
        mk_line(cur, mk_entry(cur, scen["id"]), expense_b["id"], 50)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        today = date.today().isoformat()
        r = c.get(f"/income-statement?scenario={scen['code']}&date_from={today}&date_to={today}")
        assert r.status_code == 200
        assert _account_row_value(r.text, expense_a["code"]) == "100.00"
        assert _account_row_value(r.text, expense_b["code"]) == "50.00"
        assert r.text.count("Net income") == 2  # one running line per expense group
        # The first group's running line (300 - 100 = 200) precedes the
        # second's (200 - 50 = 150) in document order.
        assert r.text.index('data-value="200.00"') < r.text.index('data-value="150.00"')


def _labeled_row_value(html: str, label: str) -> str:
    """Like _account_row_value, but for a synthetic row identified by its
    label text instead of an account code (e.g. "Prior years (unclosed)",
    which has no account of its own). Scoped to <tbody> — these reports'
    own descriptive text above the table can legitimately mention the
    same label (e.g. explaining what "Prior years" means), which would
    otherwise be found first and throw the search off by a row."""
    body = re.search(r"<tbody>.*?</tbody>", html, re.S).group(0)
    m = re.search(rf'{re.escape(label)}.*?</td>.*?data-value="(-?[\d.]+)"', body, re.S)
    assert m, f"no row found for label {label!r}"
    return m.group(1)


def _mk_backdated_entry(cur, scenario_id: int, entry_date: str, description: str) -> int:
    """mk_entry always uses CURRENT_DATE — this is the same insert with an
    explicit date, for testing the fiscal-year boundary on Trial Balance
    and the Balance Sheet."""
    cur.execute(
        "INSERT INTO journal_entries (scenario_id, entry_date, description) VALUES (%s, %s, %s) RETURNING id",
        (scenario_id, entry_date, description))
    return cur.fetchone()["id"]


def test_income_statement_compares_two_scenarios_with_variance_and_pct_of_income(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        actual = mk_scenario(cur, enforce_balance=False)
        budget = mk_scenario(cur, enforce_balance=False)
        income = mk_account(cur, account_type="income")
        expense = mk_account(cur, account_type="expense")
        mk_line(cur, mk_entry(cur, actual["id"]), income["id"], -400)
        mk_line(cur, mk_entry(cur, actual["id"]), expense["id"], 100)
        mk_line(cur, mk_entry(cur, budget["id"]), income["id"], -600)
        mk_line(cur, mk_entry(cur, budget["id"]), expense["id"], 150)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        today = date.today().isoformat()
        r = c.get(f"/income-statement?scenario={actual['code']}&compare={budget['code']}"
                 f"&date_from={today}&date_to={today}")
        assert r.status_code == 200
        # Income row: actual 400 vs budget 600 -> variance = budget - actual =
        # 200, % variance (of budget, the default) = (600-400)/600 = 33.3%.
        assert 'data-value="400.00"' in r.text
        assert 'data-value="600.00"' in r.text
        assert '200.00' in r.text
        assert '33.3%' in r.text
        # Net income: actual 300 vs budget 450 -> 33.3% again (same ratio here).
        assert _account_row_value(r.text, expense["code"]) == "100.00"
        # Expense row variance: 150 - 100 = 50.
        assert '50.00' in r.text
        # % of income on the Expenses subtotal (100/400 = 25%) and the
        # final Net income line (300/400 = 75%).
        assert "(25.0%)" in r.text
        assert "(75.0%)" in r.text


def test_income_statement_compares_against_an_income_statement_only_scenario(conn):
    # An income-statement-only (Budget Grid) scenario never takes a
    # journal entry at all — its numbers live in budget_lines instead —
    # so comparing against one used to silently show 0 for every row
    # (fn_account_balances, journal-based, found nothing to sum). This is
    # the fix: pull budget_lines for a scenario that's income-statement-
    # only, summed across every month the report's date range touches,
    # and flip budget_lines' plain-positive-target sign into the same
    # journal convention fn_account_balances returns so the existing
    # income/expense sign flip downstream still reads it correctly.
    with conn.cursor() as cur:
        user = mk_user(cur)
        actual = mk_scenario(cur, enforce_balance=False)
        budget = mk_scenario(cur, income_statement_only=True)
        income = mk_account(cur, account_type="income")
        expense = mk_account(cur, account_type="expense")
        today = date.today()
        month_start = today.replace(day=1).isoformat()
        mk_budget_line(cur, budget["id"], income["id"], 1000, period_month=month_start)
        mk_budget_line(cur, budget["id"], expense["id"], 600, period_month=month_start)
        mk_line(cur, mk_entry(cur, actual["id"]), income["id"], -1000)
        mk_line(cur, mk_entry(cur, actual["id"]), expense["id"], 450)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/income-statement?scenario={actual['code']}&compare={budget['code']}"
                 f"&date_from={month_start}&date_to={today.isoformat()}")
        assert r.status_code == 200
        # Income: actual 1000 vs budgeted 1000 -> matches exactly, 0.0%.
        assert 'data-value="1000.00"' in r.text
        assert "0.0%" in r.text
        # Expense: actual 450 vs budgeted 600 -> variance = budget - actual =
        # 150, % variance (of budget, the default) = (600-450)/600 = 25.0%.
        assert _account_row_value(r.text, expense["code"]) == "450.00"
        assert "150.00" in r.text
        assert "25.0%" in r.text
        # Net income: actual 550 (1000-450) vs budgeted 400 (1000-600) ->
        # variance = budget - actual = 400 - 550 = -150, pct = (400-550)/400 = -37.5%.
        assert "550.00" in r.text
        assert "-37.5%" in r.text
        assert "400.00" in r.text
        assert "-150.00" in r.text


def test_income_statement_no_compare_has_no_variance_column(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        income = mk_account(cur, account_type="income")
        mk_line(cur, mk_entry(cur, scen["id"]), income["id"], -100)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        today = date.today().isoformat()
        r = c.get(f"/income-statement?scenario={scen['code']}&date_from={today}&date_to={today}")
        assert r.status_code == 200
        assert "% variance" not in r.text


def test_pct_of_base_toggle_flips_variance_convention_on_every_report(conn):
    # "% variance of actual" (a checkbox next to Hide zero balances, same
    # shape everywhere) switches all three reports that show a %
    # variance column between two conventions: unchecked/default (% of
    # budget — how far actual fell from budgeted, as a % of budgeted)
    # and checked (% of actual — the same gap as a % of actual instead).
    # Denominator moves, not just the numerator's sign, so this checks
    # both states land on the actual expected number, not just "the sign
    # flipped."
    with conn.cursor() as cur:
        user = mk_user(cur)
        actual = mk_scenario(cur, enforce_balance=False)
        budget = mk_scenario(cur, enforce_balance=False)
        income = mk_account(cur, account_type="income")
        mk_line(cur, mk_entry(cur, actual["id"]), income["id"], -400)
        mk_line(cur, mk_entry(cur, budget["id"]), income["id"], -600)

        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
        variance_budget = mk_scenario(cur, enforce_balance=False)
        eid = mk_entry(cur, actual_id)
        mk_line(cur, eid, income["id"], 100, line_no=1)
        counter = mk_account(cur)
        mk_line(cur, eid, counter["id"], -100, line_no=2)
        mk_line(cur, mk_entry(cur, variance_budget["id"]), income["id"], 90)

        scen = mk_scenario(cur, income_statement_only=True)
        expense = mk_account(cur, account_type="expense")
        mk_budget_line(cur, scen["id"], expense["id"], 600, period_month="2026-08-01")
        # Explicit date literal (not mk_entry's CURRENT_DATE) — Budget
        # Grid's own query below is pinned to August 2026 specifically,
        # same reason test_budget_page_shows_budgeted_actual_and_variance
        # does the same rather than relying on "today" falling in it.
        cur.execute(
            """INSERT INTO journal_entries (scenario_id, entry_date, description)
               VALUES (%s, '2026-08-05', 'Budget grid actual') RETURNING id""",
            (actual_id,))
        eid2 = cur.fetchone()["id"]
        mk_line(cur, eid2, expense["id"], 450, line_no=1)
        mk_line(cur, eid2, counter["id"], -450, line_no=2)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        today = date.today().isoformat()

        # Income Statement: checkbox hidden with no compare, present once
        # one's picked; checked = % of actual = (400-600)/400 = -50.0%.
        r = c.get(f"/income-statement?scenario={actual['code']}&compare={budget['code']}"
                 f"&date_from={today}&date_to={today}&pct_of_base=1")
        assert 'name="pct_of_base" value="1" checked' in r.text
        assert "-50.0%" in r.text

        # Variance: baseline 100 vs compare(budget) 90, checked = % of
        # actual (compare) = (90-100)/90 = -11.1%.
        r = c.get(f"/variance?baseline=ACTUAL&compare={variance_budget['code']}&pct_of_base=1")
        assert 'name="pct_of_base" value="1" checked' in r.text
        assert "-11.1%" in r.text

        # Budget Grid: actual 450 vs budgeted 600, checked = % of actual =
        # (450-600)/450 = -33.3%.
        r = c.get(f"/budget?scenario={scen['code']}&month=2026-08&pct_of_base=1")
        assert 'name="pct_of_base" value="1" checked' in r.text
        assert "-33.3%" in r.text


def _earlier_this_year_or_none() -> str | None:
    """The last day of the previous month, if that's still this year — i.e.
    a date in the "current fiscal year but not the current month" bucket.
    None in January, when no such date exists (the fiscal year and the
    month both just started) — callers skip that part of the setup then,
    since Current Year Earnings is structurally zero anyway that month."""
    candidate = date.today().replace(day=1) - timedelta(days=1)
    return candidate.isoformat() if candidate.year == date.today().year else None


def test_trial_balance_simulates_monthly_close_with_earnings_lines(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        income = mk_account(cur, account_type="income")
        old_id = _mk_backdated_entry(cur, scen["id"], "2020-01-15", "Old income")
        mk_line(cur, old_id, income["id"], -1000)
        earlier = _earlier_this_year_or_none()
        if earlier:
            mid_id = _mk_backdated_entry(cur, scen["id"], earlier, "Earlier this year")
            mk_line(cur, mid_id, income["id"], -400)
        mk_line(cur, mk_entry(cur, scen["id"]), income["id"], -300)  # this month
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        r = c.get(f"/trial-balance?scenario={scen['code']}")
        assert r.status_code == 200
        assert _account_row_value(r.text, income["code"]) == "300.00"  # MTD only
        assert _labeled_row_value(r.text, "Prior Year Earnings (Unclosed)") == "1000.00"
        assert _labeled_row_value(r.text, "Current Year Earnings (Unclosed)") == \
            ("400.00" if earlier else "0.00")

        # raw=1 turns the simulation off: the account shows its true,
        # un-simulated lifetime total, and neither synthetic line exists.
        r_raw = c.get(f"/trial-balance?scenario={scen['code']}&raw=1")
        expected_total = 1700.00 if earlier else 1300.00
        assert _account_row_value(r_raw.text, income["code"]) == f"{expected_total:.2f}"
        assert "Unclosed" not in r_raw.text


def test_balance_sheet_simulates_monthly_close_with_earnings_lines(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        asset = mk_account(cur, account_type="asset")
        income = mk_account(cur, account_type="income")
        expense = mk_account(cur, account_type="expense")

        old_id = _mk_backdated_entry(cur, scen["id"], "2020-01-15", "Old income")
        mk_line(cur, old_id, asset["id"], 500, line_no=1)
        mk_line(cur, old_id, income["id"], -500, line_no=2)

        earlier = _earlier_this_year_or_none()
        if earlier:
            mid_id = _mk_backdated_entry(cur, scen["id"], earlier, "Earlier this year")
            mk_line(cur, mid_id, asset["id"], 400, line_no=1)
            mk_line(cur, mid_id, income["id"], -400, line_no=2)

        e2 = mk_entry(cur, scen["id"])  # this month
        mk_line(cur, e2, asset["id"], 200, line_no=1)
        mk_line(cur, e2, income["id"], -200, line_no=2)

        e3 = mk_entry(cur, scen["id"])  # this month
        mk_line(cur, e3, expense["id"], 50, line_no=1)
        mk_line(cur, e3, asset["id"], -50, line_no=2)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        expected_asset_total = 1050.00 if earlier else 650.00
        r = c.get(f"/balance-sheet?scenario={scen['code']}")
        assert r.status_code == 200
        assert "out-of-balance" not in r.text
        assert _account_row_value(r.text, asset["code"]) == f"{expected_asset_total:.2f}"
        assert _labeled_row_value(r.text, "Current Year Earnings (Unclosed)") == \
            ("550.00" if earlier else "150.00")  # (400 or 0) + (200 - 50)
        assert _labeled_row_value(r.text, "Prior Year Earnings (Unclosed)") == "500.00"

        r_raw = c.get(f"/balance-sheet?scenario={scen['code']}&raw=1")
        assert "out-of-balance" not in r_raw.text
        assert _labeled_row_value(r_raw.text, "Current earnings (unclosed)") == \
            f"{(550.00 if earlier else 150.00) + 500.00:.2f}"


def test_entries_page_filters_by_account(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct_a = mk_account(cur)
        acct_b = mk_account(cur)
        mk_line(cur, mk_entry(cur, scen["id"], "Entry A"), acct_a["id"], 10)
        mk_line(cur, mk_entry(cur, scen["id"], "Entry B"), acct_b["id"], 20)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/entries?account={acct_a['code']}")
        assert r.status_code == 200
        assert "Entry A" in r.text
        assert "Entry B" not in r.text
        assert f"postings to <span class=\"mono\">{acct_a['code']}</span>" in r.text
        # The "clear" link drops the account filter (and back, since there's
        # none here) but keeps nothing else stray.
        m = re.search(r'href="/entries\?([^"]*)">clear</a>', r.text)
        assert m, "no clear link found"
        qs = parse_qs(m.group(1).replace("&amp;", "&"), keep_blank_values=True)
        assert qs.get("account", [""]) == [""]
        assert qs.get("back", [""]) == [""]

        r_csv = c.get(f"/entries/export.csv?account={acct_a['code']}")
        assert acct_a["code"] in r_csv.text
        assert acct_b["code"] not in r_csv.text


def test_entries_page_never_shows_staging_entries(conn):
    # The Journal is exclusively for posted, non-staging scenarios — a
    # pending Staging entry must never appear here, regardless of the
    # scenario filter (unfiltered, explicitly filtered to something else,
    # or a hand-edited scenario=STAGING query string), and Staging must
    # not be offered as a choice in the Scenario dropdown at all.
    with conn.cursor() as cur:
        user = mk_user(cur)
        eid, _, _ = _mk_staged_entry(cur, description="Staged, should never show")
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        r = c.get("/entries")
        assert r.status_code == 200
        assert "Staged, should never show" not in r.text
        assert "STAGING" not in r.text
        # Scenario is the one filter dropdown with no "All" option (Account
        # and Payee keep theirs) — isolate its <select> before checking.
        m = re.search(r'<select name="scenario">.*?</select>', r.text, re.DOTALL)
        assert m, "scenario select not found"
        assert ">All</option>" not in m.group(0)

        # Even a hand-edited query string asking for the Staging scenario
        # by code doesn't leak it in.
        r_forced = c.get("/entries?scenario=STAGING")
        assert "Staged, should never show" not in r_forced.text

        r_csv = c.get("/entries/export.csv")
        assert "Staged, should never show" not in r_csv.text


def test_dateformat_filter_wraps_iso_text_in_a_date_fmt_span(conn):
    # No-JS fallback text is plain ISO, same shape money() falls back to
    # American-default text — date-format.js rewrites the *displayed*
    # text client-side from data-value, never what's here.
    assert str(dateformat(date(2026, 8, 26))) == \
        '<span class="date-fmt" data-value="2026-08-26">2026-08-26</span>'
    assert str(dateformat(None)) == ""


def test_entries_page_and_settings_page_offer_date_format(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        mk_line(cur, mk_entry(cur, scen["id"], "Dated entry"), mk_account(cur)["id"], 10)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        r = c.get("/entries")
        assert f'class="date-fmt" data-value="{date.today().isoformat()}"' in r.text

        r_settings = c.get("/settings")
        assert '<select id="date-format-select">' in r_settings.text
        for opt in ('value="iso"', 'value="us"', 'value="eu"', 'value="long"'):
            assert opt in r_settings.text


def test_settings_page_offers_a_font_bundle_picker(conn):
    # Font is a separate choice from Theme (data-font vs. data-theme —
    # see style.css's font-bundle block and font.js) — a handful of
    # named bundles, not a free-text typeface field, and one of them
    # (Classic Serif) is the one that renders actual numbers in serif
    # rather than the app's usual monospace figures.
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/settings")
        assert '<select id="font-select">' in r.text
        for opt in ('value="system"', 'value="serif"', 'value="modern"', 'value="mono"'):
            assert opt in r.text
        assert "Classic Serif" in r.text

        r_home = c.get("/")
        assert 'font.js' in r_home.text


def test_entries_page_hide_reversed_excludes_both_sides_of_the_pair(conn):
    # "Hide reversed entries and their reversals" has to drop both halves
    # of a reversal — the original (reverses_entry_id IS NULL but it's
    # someone else's target) and the reversal itself (reverses_entry_id
    # set) — not just one side.
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct1 = mk_account(cur)
        acct2 = mk_account(cur)
        original = mk_entry(cur, scen["id"], "Original entry")
        mk_line(cur, original, acct1["id"], 40)
        cur.execute(
            """INSERT INTO journal_entries
                   (scenario_id, entry_date, description, reverses_entry_id)
               VALUES (%s, CURRENT_DATE, 'Reversal entry', %s) RETURNING id""",
            (scen["id"], original))
        reversal = cur.fetchone()["id"]
        mk_line(cur, reversal, acct1["id"], -40)
        untouched = mk_entry(cur, scen["id"], "Untouched entry")
        mk_line(cur, untouched, acct2["id"], 15)
    conn.commit()

    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        r = c.get(f"/entries?scenario={scen['code']}")
        assert "Original entry" in r.text
        assert "Reversal entry" in r.text
        assert "Untouched entry" in r.text

        r = c.get(f"/entries?scenario={scen['code']}&hide_reversed=1")
        assert "Original entry" not in r.text
        assert "Reversal entry" not in r.text
        assert "Untouched entry" in r.text

        r_csv = c.get(f"/entries/export.csv?scenario={scen['code']}&hide_reversed=1")
        assert "Original entry" not in r_csv.text
        assert "Reversal entry" not in r_csv.text
        assert "Untouched entry" in r_csv.text


def test_entries_page_offers_select_entries_with_reverse_disabled_until_checked(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        eid = mk_entry(cur, scen["id"], "Reversible entry")
        mk_line(cur, eid, acct["id"], 40)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/entries?scenario={scen['code']}")
        assert 'id="select-toggle"' in r.text
        # Reverse itself is no longer select-only — it's always on the
        # page (so its existence doesn't depend on discovering Select
        # first), just disabled until something's actually checked.
        assert 'id="reverse-btn" disabled' in r.text
        assert 'id="reverse-btn" class="select-only"' not in r.text
        assert f'value="{eid}"' in r.text
        # The old per-entry button is gone — bulk Reverse (checked +
        # the top button) is the only mechanism now.
        assert "Reverse this entry" not in r.text


def test_entries_bulk_reverse_posts_a_reversal_for_every_checked_entry(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        eid1 = mk_entry(cur, scen["id"], "First entry")
        mk_line(cur, eid1, acct["id"], 40)
        eid2 = mk_entry(cur, scen["id"], "Second entry")
        mk_line(cur, eid2, acct["id"], 25)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post("/entries/reverse", data={
            "entry_id": [str(eid1), str(eid2)], "csrf_token": csrf_token,
        })
        assert r.status_code == 303
        assert "ok=" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM journal_entries WHERE reverses_entry_id = %s", (eid1,))
        assert cur.fetchone()["n"] == 1
        cur.execute("SELECT COUNT(*) AS n FROM journal_entries WHERE reverses_entry_id = %s", (eid2,))
        assert cur.fetchone()["n"] == 1


def test_entries_bulk_reverse_requires_at_least_one_entry(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post("/entries/reverse", data={"csrf_token": csrf_token})
        assert "err=" in r.headers["location"]


def test_entries_bulk_reverse_skips_an_already_reversed_entry_but_still_reverses_the_rest(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        already = mk_entry(cur, scen["id"], "Already reversed")
        mk_line(cur, already, acct["id"], 10)
        cur.execute(
            """INSERT INTO journal_entries
                   (scenario_id, entry_date, description, reverses_entry_id)
               VALUES (%s, CURRENT_DATE, 'Its own reversal', %s) RETURNING id""",
            (scen["id"], already))
        mk_line(cur, cur.fetchone()["id"], acct["id"], -10)
        fresh = mk_entry(cur, scen["id"], "Not yet reversed")
        mk_line(cur, fresh, acct["id"], 15)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post("/entries/reverse", data={
            "entry_id": [str(already), str(fresh)], "csrf_token": csrf_token,
        })
        assert "ok=" in r.headers["location"]
        assert "err=" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM journal_entries WHERE reverses_entry_id = %s", (fresh,))
        assert cur.fetchone()["n"] == 1
        # Still just the one reversal already_reversed had going in.
        cur.execute("SELECT COUNT(*) AS n FROM journal_entries WHERE reverses_entry_id = %s", (already,))
        assert cur.fetchone()["n"] == 1


def test_entries_tags_add_applies_to_every_selected_entry(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        eid1 = mk_entry(cur, scen["id"], "First entry")
        mk_line(cur, eid1, acct["id"], 10)
        eid2 = mk_entry(cur, scen["id"], "Second entry")
        mk_line(cur, eid2, acct["id"], 20)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post("/entries/tags", data={
            "entry_id": [str(eid1), str(eid2)], "tag": "groceries", "action": "add",
            "csrf_token": csrf_token,
        })
        assert r.status_code == 200
        assert r.json()["ok"] is True

    with conn.cursor() as cur:
        cur.execute("""SELECT COUNT(*) AS n FROM journal_entry_tags jet
                         JOIN tags tg ON tg.id = jet.tag_id
                        WHERE tg.name = 'groceries' AND jet.entry_id = ANY(%s)""",
                   ([eid1, eid2],))
        assert cur.fetchone()["n"] == 2


def test_entries_tags_remove_only_touches_entries_that_have_it(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        tagged = mk_entry(cur, scen["id"], "Already tagged")
        mk_line(cur, tagged, acct["id"], 10)
        untagged = mk_entry(cur, scen["id"], "Never tagged")
        mk_line(cur, untagged, acct["id"], 5)
        cur.execute("INSERT INTO tags (name) VALUES ('urgent') RETURNING id")
        tag_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO journal_entry_tags (entry_id, tag_id) VALUES (%s, %s)",
                   (tagged, tag_id))
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        # Both checked, only one actually has the tag — removing it should
        # be a harmless no-op for the entry that never had it.
        r = c.post("/entries/tags", data={
            "entry_id": [str(tagged), str(untagged)], "tag": "urgent", "action": "remove",
            "csrf_token": csrf_token,
        })
        assert r.status_code == 200

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM journal_entry_tags WHERE entry_id = %s", (tagged,))
        assert cur.fetchone()["n"] == 0


def test_entries_tags_requires_entries_selected_and_a_known_action(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]

        r = c.post("/entries/tags", data={"tag": "groceries", "action": "add", "csrf_token": csrf_token})
        assert r.status_code == 400
        assert r.json()["ok"] is False

        r = c.post("/entries/tags", data={
            "entry_id": "1", "tag": "groceries", "action": "delete", "csrf_token": csrf_token,
        })
        assert r.status_code == 400
        assert r.json()["ok"] is False


def test_entries_edit_description_updates_a_posted_entry(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        eid = mk_entry(cur, scen["id"], "Grocreies (typo)")
        mk_line(cur, eid, acct["id"], 10)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post(f"/entries/{eid}/edit-description",
                   data={"description": "Original, fixed", "csrf_token": csrf_token})
        assert r.status_code == 303
        assert "ok=" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT description FROM journal_entries WHERE id = %s", (eid,))
        assert cur.fetchone()["description"] == "Original, fixed"


def test_entries_edit_description_rejects_an_empty_description(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        eid = mk_entry(cur, scen["id"], "Keep me")
        mk_line(cur, eid, acct["id"], 10)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post(f"/entries/{eid}/edit-description",
                   data={"description": "   ", "csrf_token": csrf_token})
        assert "err=" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT description FROM journal_entries WHERE id = %s", (eid,))
        assert cur.fetchone()["description"] == "Keep me"


def test_entries_page_description_edit_form_is_not_nested_inside_the_select_form(conn):
    # A <form> can't nest inside another <form> — the browser's parser
    # silently drops a nested one, leaving its inputs/button as loose
    # children with no form at all, so the "Save" button would do
    # nothing. The Journal's outer #entries-select-form (Reverse/Edit
    # tags) wraps only the toolbar, not the entries below it, precisely
    # to avoid that — each entry's own checkbox joins that form via
    # form="entries-select-form" instead of DOM nesting. Checked here as
    # a literal string match on the real opening <form ...> tag, not
    # just its inner fields, since that's exactly what a silently-
    # dropped nested form would still contain.
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        eid = mk_entry(cur, scen["id"], "Nesting check")
        mk_line(cur, eid, acct["id"], 10)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/entries?scenario={scen['code']}")
        assert f'<form method="post" action="/entries/{eid}/edit-description"' in r.text
        assert f'value="{eid}" class="entry-check" form="entries-select-form"' in r.text


def test_entries_page_filters_by_amount(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        mk_line(cur, mk_entry(cur, scen["id"], "Small one"), acct["id"], 10)
        mk_line(cur, mk_entry(cur, scen["id"], "Big one"), acct["id"], 20)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        r = c.get(f"/entries?scenario={scen['code']}&amount_op=gte&amount_value=15")
        assert r.status_code == 200
        assert "Big one" in r.text
        assert "Small one" not in r.text

        r = c.get(f"/entries?scenario={scen['code']}&amount_op=lt&amount_value=15")
        assert "Small one" in r.text
        assert "Big one" not in r.text

        r = c.get(f"/entries?scenario={scen['code']}&amount_op=eq&amount_value=10")
        assert "Small one" in r.text
        assert "Big one" not in r.text

        # A hand-edited/garbage amount_value doesn't 500 — it's just ignored.
        r = c.get(f"/entries?scenario={scen['code']}&amount_op=gte&amount_value=not-a-number")
        assert r.status_code == 200
        assert "Small one" in r.text and "Big one" in r.text

        r_csv = c.get(f"/entries/export.csv?scenario={scen['code']}&amount_op=gte&amount_value=15")
        assert "Big one" in r_csv.text
        assert "Small one" not in r_csv.text


def test_entries_page_filters_by_amount_between(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        mk_line(cur, mk_entry(cur, scen["id"], "Too small"), acct["id"], 5)
        mk_line(cur, mk_entry(cur, scen["id"], "Just right"), acct["id"], 15)
        mk_line(cur, mk_entry(cur, scen["id"], "Too big"), acct["id"], 25)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        r = c.get(f"/entries?scenario={scen['code']}&amount_op=between&amount_value=10&amount_value2=20")
        assert r.status_code == 200
        assert "Just right" in r.text
        assert "Too small" not in r.text and "Too big" not in r.text

        # Bounds given the other way round still work — sorted server-side.
        r = c.get(f"/entries?scenario={scen['code']}&amount_op=between&amount_value=20&amount_value2=10")
        assert "Just right" in r.text
        assert "Too small" not in r.text and "Too big" not in r.text

        # Only one bound given — "between" needs both, so this is a no-op
        # filter (same as "Any"), not a crash and not treated as one-sided.
        r = c.get(f"/entries?scenario={scen['code']}&amount_op=between&amount_value=10")
        assert "Too small" in r.text and "Just right" in r.text and "Too big" in r.text


def test_amount_value_fields_stay_hidden_until_an_operator_is_picked(conn):
    # Both amount value boxes are server-rendered off amount_op, same as
    # the "between" field always was — the plain (single-bound) value box
    # used to stay in the DOM and visible even at "Any", which is what made
    # the filter bar look like it always had a lone, unlabeled empty box
    # sitting there. Now both share the same hidden-until-relevant
    # treatment. Both boxes live inside one shared .field (.amount-range)
    # so "and" can sit between them instead of as the second box's own
    # label above it; "between" mode's own boxes get distinguishing
    # Min/Max placeholders since two boxes with an identical hint don't
    # say which bound is which, and the single-box case says "Value"
    # rather than the old "0.00" (which read like a live amount, not a
    # hint for what to type).
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        for url in ("/entries", "/staging"):
            r = c.get(url)
            assert '<label class="field" id="amount-value-field" style="flex: none;" hidden>' in r.text

            r = c.get(f"{url}?amount_op=gte")
            assert '<label class="field" id="amount-value-field" style="flex: none;" >' in r.text
            assert 'placeholder="Value"' in r.text
            assert 'id="amount-and" hidden' in r.text
            assert 'id="amount-value2-input"' in r.text and 'hidden' in r.text

            r = c.get(f"{url}?amount_op=between")
            assert '<label class="field" id="amount-value-field" style="flex: none;" >' in r.text
            assert 'id="amount-and" >' in r.text
            assert '<input type="text" name="amount_value2" id="amount-value2-input"' in r.text
            assert 'placeholder="Min"' in r.text and 'placeholder="Max"' in r.text


def test_entries_page_clear_filters_link_only_shows_when_a_filter_is_active(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})

        # No filters: rendered, but disabled — no href, so it's not a real
        # link (unfocusable, unclickable) rather than absent outright.
        r = c.get("/entries")
        assert 'class="button-link disabled"' in r.text
        assert 'href="/entries">Clear filters</a>' not in r.text

        r = c.get("/entries?qtext=rent")
        assert 'href="/entries">Clear filters</a>' in r.text


def test_entries_page_filter_form_offers_account_and_payee_dropdowns(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        acct = mk_account(cur)
        payee = mk_payee(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/entries")
        assert r.status_code == 200
        account_select = re.search(r'<select name="account">.*?</select>', r.text, re.S).group(0)
        assert f'value="{acct["code"]}"' in account_select
        payee_select = re.search(r'<select name="payee">.*?</select>', r.text, re.S).group(0)
        assert f'value="{payee["name"]}"' in payee_select


def test_entries_page_filters_by_payee(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        payee_a = mk_payee(cur)
        payee_b = mk_payee(cur)
        mk_line(cur, mk_entry(cur, scen["id"], "Entry A", payee_id=payee_a["id"]), acct["id"], 10)
        mk_line(cur, mk_entry(cur, scen["id"], "Entry B", payee_id=payee_b["id"]), acct["id"], 20)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/entries?payee={payee_a['name']}")
        assert r.status_code == 200
        assert "Entry A" in r.text
        assert "Entry B" not in r.text
        assert f'entries for payee <span class="mono">{payee_a["name"]}</span>' in r.text
        m = re.search(r'href="/entries\?([^"]*)">clear</a>', r.text)
        assert m, "no clear link found"
        qs = parse_qs(m.group(1).replace("&amp;", "&"), keep_blank_values=True)
        assert qs.get("payee", [""]) == [""]

        r_csv = c.get(f"/entries/export.csv?payee={payee_a['name']}")
        assert "Entry A" in r_csv.text
        assert "Entry B" not in r_csv.text


def test_payees_page_amount_links_to_filtered_journal(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        acct = mk_account(cur)
        payee = mk_payee(cur)
        empty_payee = mk_payee(cur)
        mk_line(cur, mk_entry(cur, scen["id"], payee_id=payee["id"]), acct["id"], 10)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/payees")
        assert r.status_code == 200
        # The test DB is shared across the whole pytest run, so anchor on
        # this payee's own row rather than the first count-of-1 link found
        # anywhere on the page. The name sits in its own
        # .entity-name-label span now (payees.html's Edit toggle swaps it
        # for a rename form in place — see that template), not bare
        # inside the <td>.
        m = re.search(
            rf'<span class="entity-name-label">{payee["name"]}</span>.*?'
            r'<a class="amount-link" href="([^"]+)">1</a>',
            r.text, re.S)
        assert m, "no amount-link found for the payee with one entry"
        qs = parse_qs(urlparse(m.group(1).replace("&amp;", "&")).query)
        assert qs["payee"] == [payee["name"]]
        back_path = urlparse(unquote(qs["back"][0])).path
        assert back_path == "/payees"
        # A payee with no entries at all isn't a link — nothing to click through to.
        empty_row = re.search(
            rf'<span class="entity-name-label">{empty_payee["name"]}</span>.*?</tr>',
            r.text, re.S)
        assert empty_row and "amount-link" not in empty_row.group(0)


def _csrf(c, conn):
    """The csrf_token in c's own current session — a version of the
    "log in, then fetch csrf_token from the sessions row" boilerplate
    every state-changing test above repeats inline, factored out for the
    Payees/Tags tests below since several of them need a fresh token more
    than once per test (rename, then delete; two merges)."""
    with conn.cursor() as cur:
        cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                   (c.cookies["postwarden_session"],))
        return cur.fetchone()["csrf_token"]


def test_payee_rename_updates_the_name_and_leaves_entries_pointing_at_it(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        payee = mk_payee(cur, name="Old Name")
        scen = mk_scenario(cur, enforce_balance=False)
        eid = mk_entry(cur, scen["id"], payee_id=payee["id"])
        mk_line(cur, eid, mk_account(cur)["id"], 10)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r = c.post(f"/payees/{payee['id']}/rename",
                  data={"name": "New Name", "csrf_token": csrf_token})
        assert r.status_code == 303
        assert "New+Name" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT name FROM payees WHERE id = %s", (payee["id"],))
        assert cur.fetchone()["name"] == "New Name"
        # The entry itself never stored the payee's name — only payee_id —
        # so it still resolves to the same row under its new name.
        cur.execute(
            """SELECT p.name FROM journal_entries e JOIN payees p ON p.id = e.payee_id
               WHERE e.id = %s""", (eid,))
        assert cur.fetchone()["name"] == "New Name"


def test_payee_rename_rejects_an_empty_name(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        payee = mk_payee(cur, name="Keep me")
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r = c.post(f"/payees/{payee['id']}/rename",
                  data={"name": "   ", "csrf_token": csrf_token})
        assert "err=" in r.headers["location"]
    with conn.cursor() as cur:
        cur.execute("SELECT name FROM payees WHERE id = %s", (payee["id"],))
        assert cur.fetchone()["name"] == "Keep me"


def test_payee_delete_removes_the_row_and_blanks_referencing_entries(conn):
    # payees(id) is ON DELETE SET NULL on every table that references it
    # (journal_entries, scheduled_entries, entry_templates) — this is what
    # makes Delete safe by construction rather than blocked or cascading;
    # see /payees/{id}/delete's own comment in main.py.
    with conn.cursor() as cur:
        user = mk_user(cur)
        payee = mk_payee(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        eid = mk_entry(cur, scen["id"], payee_id=payee["id"])
        mk_line(cur, eid, mk_account(cur)["id"], 10)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r = c.post(f"/payees/{payee['id']}/delete", data={"csrf_token": csrf_token})
        assert r.status_code == 303
        assert "ok=" in r.headers["location"]

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM payees WHERE id = %s", (payee["id"],))
        assert cur.fetchone() is None
        cur.execute("SELECT payee_id FROM journal_entries WHERE id = %s", (eid,))
        assert cur.fetchone()["payee_id"] is None  # entry itself untouched otherwise
        cur.execute("SELECT COUNT(*) AS n FROM journal_lines WHERE entry_id = %s", (eid,))
        assert cur.fetchone()["n"] == 1


def test_payee_delete_rejects_an_unknown_id(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r = c.post("/payees/999999999/delete", data={"csrf_token": csrf_token})
        assert "err=" in r.headers["location"]


def test_payee_toggle_active_flash_names_which_way_it_went(conn):
    # Archive/Unarchive on the page — the flash message used to be a
    # generic "Payee updated" regardless of direction; RETURNING the new
    # state is what lets it actually say "archived" vs "unarchived".
    with conn.cursor() as cur:
        user = mk_user(cur)
        payee = mk_payee(cur, name="Toggle Me")
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r1 = c.post(f"/payees/{payee['id']}/toggle-active", data={"csrf_token": csrf_token})
        assert "archived" in r1.headers["location"]
        r2 = c.post(f"/payees/{payee['id']}/toggle-active", data={"csrf_token": csrf_token})
        assert "unarchived" in r2.headers["location"]


def test_payee_merge_repoints_entries_scheduled_entries_and_templates(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        survivor = mk_payee(cur, name="Survivor")
        other = mk_payee(cur, name="Other")
        scen = mk_scenario(cur, enforce_balance=False)
        eid1 = mk_entry(cur, scen["id"], payee_id=survivor["id"])
        mk_line(cur, eid1, mk_account(cur)["id"], 10)
        eid2 = mk_entry(cur, scen["id"], payee_id=other["id"])
        mk_line(cur, eid2, mk_account(cur)["id"], 20)
        cur.execute(
            """INSERT INTO scheduled_entries
                   (description, payee_id, target_scenario_id, interval_unit, next_date)
               VALUES ('Sched', %s, %s, 'month', CURRENT_DATE + 30)""",
            (other["id"], scen["id"]))
        cur.execute(
            "INSERT INTO entry_templates (name, description, payee_id) VALUES (%s, %s, %s)",
            ("Merge test template", "Tpl", other["id"]))
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r = c.post("/payees/merge", data={
            "payee_id": [str(survivor["id"]), str(other["id"])],
            "target_name": "Merged Name", "csrf_token": csrf_token,
        })
        assert r.status_code == 303
        loc = r.headers["location"]
        assert "ok=" in loc
        assert "Merged+Name" in loc
        # Only eid2 actually needed repointing — eid1 already belonged to
        # the survivor row, so it isn't counted as "affected".
        assert "1+entry+affected" in loc

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM payees WHERE id = %s", (other["id"],))
        assert cur.fetchone() is None  # the merged-away row is gone
        cur.execute("SELECT name FROM payees WHERE id = %s", (survivor["id"],))
        assert cur.fetchone()["name"] == "Merged Name"
        cur.execute("SELECT payee_id FROM journal_entries WHERE id = %s", (eid2,))
        assert cur.fetchone()["payee_id"] == survivor["id"]
        cur.execute("SELECT payee_id FROM scheduled_entries WHERE description = 'Sched'")
        assert cur.fetchone()["payee_id"] == survivor["id"]
        cur.execute(
            "SELECT payee_id FROM entry_templates WHERE name = 'Merge test template'")
        assert cur.fetchone()["payee_id"] == survivor["id"]


def test_payee_merge_requires_at_least_two_selected(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        payee = mk_payee(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r = c.post("/payees/merge", data={
            "payee_id": [str(payee["id"])], "target_name": "Whatever",
            "csrf_token": csrf_token,
        })
        assert "err=" in r.headers["location"]


def test_tags_page_lists_tags_with_entry_counts_and_links(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        tag = mk_tag(cur)
        eid = mk_entry(cur, scen["id"], "Tagged entry")
        mk_line(cur, eid, mk_account(cur)["id"], 10)
        cur.execute("INSERT INTO journal_entry_tags (entry_id, tag_id) VALUES (%s, %s)",
                   (eid, tag["id"]))
        empty_tag = mk_tag(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/tags")
        assert r.status_code == 200
        m = re.search(
            rf'<span class="entity-name-label">{tag["name"]}</span>.*?'
            r'<a class="amount-link" href="([^"]+)">1</a>',
            r.text, re.S)
        assert m, "no amount-link found for the tag with one entry"
        qs = parse_qs(urlparse(m.group(1).replace("&amp;", "&")).query)
        assert qs["tags"] == [tag["name"]]
        empty_row = re.search(
            rf'<span class="entity-name-label">{empty_tag["name"]}</span>.*?</tr>',
            r.text, re.S)
        assert empty_row and "amount-link" not in empty_row.group(0)
        assert "Archive" in r.text


def test_tag_create_rename_delete_round_trip(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)

        r1 = c.post("/tags", data={"name": "zzcreatetagtest", "csrf_token": csrf_token})
        assert "ok=" in r1.headers["location"]
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM tags WHERE name = 'zzcreatetagtest'")
            tag_id = cur.fetchone()["id"]

        r2 = c.post(f"/tags/{tag_id}/rename",
                   data={"name": "renamed-tag", "csrf_token": csrf_token})
        assert "ok=" in r2.headers["location"]
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM tags WHERE id = %s", (tag_id,))
            assert cur.fetchone()["name"] == "renamed-tag"

        # An invalid name (uppercase/punctuation the CHECK constraint
        # rejects) fails through _parse_tags before it ever reaches SQL.
        r3 = c.post(f"/tags/{tag_id}/rename",
                   data={"name": "Not Valid!", "csrf_token": csrf_token})
        assert "err=" in r3.headers["location"]

        r4 = c.post(f"/tags/{tag_id}/delete", data={"csrf_token": csrf_token})
        assert "ok=" in r4.headers["location"]
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM tags WHERE id = %s", (tag_id,))
        assert cur.fetchone() is None


def test_tag_toggle_active_flash_names_which_way_it_went(conn):
    # Same shape as the payee version above — Archive/Unarchive, RETURNING
    # the new state so the flash message says which way it went.
    with conn.cursor() as cur:
        user = mk_user(cur)
        tag = mk_tag(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r1 = c.post(f"/tags/{tag['id']}/toggle-active", data={"csrf_token": csrf_token})
        assert "archived" in r1.headers["location"]
        r2 = c.post(f"/tags/{tag['id']}/toggle-active", data={"csrf_token": csrf_token})
        assert "unarchived" in r2.headers["location"]


def test_archived_tag_is_hidden_from_the_tag_input_suggestion_list(conn):
    # all_tags() (the #tags-data blob every tag-input reads for
    # autocomplete) filters WHERE is_active — an archived tag stops being
    # offered as something new to pick, same as an archived payee drops
    # out of active_payees.
    with conn.cursor() as cur:
        user = mk_user(cur)
        active_tag = mk_tag(cur)
        archived_tag = mk_tag(cur)
        cur.execute("UPDATE tags SET is_active = FALSE WHERE id = %s", (archived_tag["id"],))
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/entries")
        blob = json.loads(
            re.search(r'id="tags-data">(.*?)</script>', r.text, re.S).group(1))
        assert active_tag["name"] in blob
        assert archived_tag["name"] not in blob


def test_tagging_an_entry_with_an_archived_tags_name_reactivates_it(conn):
    # _sync_entry_tags' ON CONFLICT reactivates rather than a no-op update
    # — typing an old tag's name back onto an entry is the same "back in
    # use" signal quick_create_payee already treats a reused payee name
    # as. Exercised through the real /entries POST route, not _sync_tags
    # directly, so this also confirms entity-manage.js's counterpart on
    # the Journal side (tags.js's tag-input) hits the same path.
    with conn.cursor() as cur:
        user = mk_user(cur)
        tag = mk_tag(cur, name="archivedtag")
        cur.execute("UPDATE tags SET is_active = FALSE WHERE id = %s", (tag["id"],))
        acct1, acct2 = mk_account(cur), mk_account(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r = c.post("/entries", data={
            "csrf_token": csrf_token, "entry_date": "2026-01-01",
            "scenario_id": str(actual_id), "description": "Reuses an archived tag",
            "tags": "archivedtag",
            "account": [acct1["code"], acct2["code"]],
            "debit": ["10", ""], "credit": ["", "10"], "memo": ["", ""],
        })
        assert "ok=" in r.headers["location"]
    with conn.cursor() as cur:
        cur.execute("SELECT is_active FROM tags WHERE id = %s", (tag["id"],))
        assert cur.fetchone()["is_active"] is True


def test_tag_delete_removes_it_from_every_entry_that_had_it(conn):
    # journal_entry_tags/scheduled_entry_tags/entry_template_tags all
    # reference tags(id) ON DELETE CASCADE (unlike payees' SET NULL) —
    # deleting a tag drops the association row entirely.
    with conn.cursor() as cur:
        user = mk_user(cur)
        tag = mk_tag(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        eid = mk_entry(cur, scen["id"])
        mk_line(cur, eid, mk_account(cur)["id"], 10)
        cur.execute("INSERT INTO journal_entry_tags (entry_id, tag_id) VALUES (%s, %s)",
                   (eid, tag["id"]))
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r = c.post(f"/tags/{tag['id']}/delete", data={"csrf_token": csrf_token})
        assert "ok=" in r.headers["location"]
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM journal_entry_tags WHERE entry_id = %s", (eid,))
        assert cur.fetchone()["n"] == 0
        # The entry and its line are both untouched — only the tag association is gone.
        cur.execute("SELECT 1 FROM journal_entries WHERE id = %s", (eid,))
        assert cur.fetchone() is not None


def test_tag_merge_dedupes_when_an_entry_already_carries_both_tags(conn):
    # The case _parse_tags/entity-manage.js can't prevent at the source —
    # an entry tagged with *both* tags being merged — is exactly what the
    # "INSERT ... ON CONFLICT DO NOTHING" pass in /tags/merge exists for
    # (see its own comment in main.py): a plain UPDATE tag_id would hit
    # journal_entry_tags' (entry_id, tag_id) primary key here.
    with conn.cursor() as cur:
        user = mk_user(cur)
        survivor = mk_tag(cur)
        other = mk_tag(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        both = mk_entry(cur, scen["id"], "Has both tags")
        mk_line(cur, both, mk_account(cur)["id"], 10)
        only_other = mk_entry(cur, scen["id"], "Has only the merged-away tag")
        mk_line(cur, only_other, mk_account(cur)["id"], 20)
        cur.execute(
            "INSERT INTO journal_entry_tags (entry_id, tag_id) VALUES (%s, %s), (%s, %s), (%s, %s)",
            (both, survivor["id"], both, other["id"], only_other, other["id"]))
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r = c.post("/tags/merge", data={
            "tag_id": [str(survivor["id"]), str(other["id"])],
            "target_name": "merged-tag", "csrf_token": csrf_token,
        })
        assert r.status_code == 303
        loc = r.headers["location"]
        assert "ok=" in loc
        assert "2+entries" in loc  # both entries carried the merged-away tag

    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM tags WHERE id = %s", (other["id"],))
        assert cur.fetchone() is None
        cur.execute(
            "SELECT COUNT(*) AS n FROM journal_entry_tags WHERE entry_id = %s AND tag_id = %s",
            (both, survivor["id"]))
        assert cur.fetchone()["n"] == 1  # not duplicated despite already having it
        cur.execute(
            "SELECT 1 FROM journal_entry_tags WHERE entry_id = %s AND tag_id = %s",
            (only_other, survivor["id"]))
        assert cur.fetchone() is not None  # picked up the survivor's tag


def test_tag_merge_requires_at_least_two_selected(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        tag = mk_tag(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        csrf_token = _csrf(c, conn)
        r = c.post("/tags/merge", data={
            "tag_id": [str(tag["id"])], "target_name": "whatever",
            "csrf_token": csrf_token,
        })
        assert "err=" in r.headers["location"]


def test_sidebar_lists_tags_right_after_payees(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/")
        m = re.search(r'href="/payees"[^>]*>Payees</a>\s*<a href="/tags"', r.text)
        assert m, "Tags does not immediately follow Payees in the sidebar"


def test_dashboard_and_scheduled_staging_banners_are_flash_warn_not_flash_ok(conn):
    # "N entries waiting in Staging" is a pending state, not a success —
    # it moved from .flash-ok (green) to .flash-warn (amber); see
    # style.css's own comment on .flash-warn for why.
    with conn.cursor() as cur:
        user = mk_user(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO scheduled_entries
                   (description, target_scenario_id, interval_unit, next_date)
               VALUES ('Banner check', %s, 'month', CURRENT_DATE) RETURNING id""",
            (actual_id,))
        sched_id = cur.fetchone()["id"]
        cur.execute("SELECT id FROM scenarios WHERE is_staging")
        staging_id = cur.fetchone()["id"]
        cur.execute(
            """INSERT INTO journal_entries
                   (scenario_id, entry_date, description, scheduled_entry_id)
               VALUES (%s, CURRENT_DATE, 'Banner check', %s) RETURNING id""",
            (staging_id, sched_id))
        eid = cur.fetchone()["id"]
        acct1, acct2 = mk_account(cur), mk_account(cur)
        mk_line(cur, eid, acct1["id"], 5, line_no=1)
        mk_line(cur, eid, acct2["id"], -5, line_no=2)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        for url in ("/", "/scheduled"):
            r = c.get(url)
            assert 'class="flash flash-warn"' in r.text
            assert 'class="flash flash-ok"' not in r.text


def test_income_statement_amounts_link_to_filtered_journal(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        income = mk_account(cur, account_type="income")
        mk_line(cur, mk_entry(cur, scen["id"]), income["id"], -100)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        today = date.today().isoformat()
        r = c.get(f"/income-statement?scenario={scen['code']}&date_from={today}&date_to={today}")
        assert r.status_code == 200
        m = re.search(r'<a class="amount-link" href="([^"]+)">', r.text)
        assert m, "no amount-link found"
        qs = parse_qs(urlparse(m.group(1).replace("&amp;", "&")).query)
        assert qs["scenario"] == [scen["code"]]
        assert qs["date_from"] == [today]
        assert qs["date_to"] == [today]
        assert qs["account"] == [income["code"]]
        back_path = urlparse(unquote(qs["back"][0])).path
        assert back_path == "/income-statement"


def test_balance_sheet_amounts_link_to_filtered_journal(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        asset = mk_account(cur, account_type="asset")
        mk_line(cur, mk_entry(cur, scen["id"]), asset["id"], 100)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/balance-sheet?scenario={scen['code']}")
        assert r.status_code == 200
        m = re.search(r'<a class="amount-link" href="([^"]+)">', r.text)
        assert m, "no amount-link found"
        qs = parse_qs(urlparse(m.group(1).replace("&amp;", "&")).query)
        assert qs["scenario"] == [scen["code"]]
        assert qs["account"] == [asset["code"]]
        back_path = urlparse(unquote(qs["back"][0])).path
        assert back_path == "/balance-sheet"


def test_trial_balance_rolls_up_a_subdivided_summary_account(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        root = mk_account(cur, account_type="asset", postable=False)            # depth 1
        current = mk_account(cur, account_type="asset", parent_id=root["id"],
                             postable=False)                                    # depth 2
        leaf_a = mk_account(cur, account_type="asset", parent_id=current["id"])  # depth 3
        leaf_b = mk_account(cur, account_type="asset", parent_id=current["id"])  # depth 3
        mk_line(cur, mk_entry(cur, scen["id"]), leaf_a["id"], 300)
        mk_line(cur, mk_entry(cur, scen["id"]), leaf_b["id"], 200)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/trial-balance?scenario={scen['code']}")
        assert r.status_code == 200
        # "Current" never received a posting directly, but rolls up both
        # leaves under it; the root rolls up "Current" in turn.
        assert _account_row_value(r.text, current["code"]) == "500.00"
        assert _account_row_value(r.text, root["code"]) == "500.00"
        # Rendered as a collapsible summary row (has descendants) ...
        m = re.search(rf'data-id="{current["id"]}"[^>]*data-has-children="(\d)"', r.text)
        assert m and m.group(1) == "1"
        # ... whose amount is plain text, not a link — it spans two
        # accounts, so no single Journal filter captures it. Leaves stay
        # individually clickable.
        assert f"account={leaf_a['code']}" in r.text
        assert f"account={current['code']}" not in r.text


def test_balance_sheet_rolls_up_a_subdivided_summary_account(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, enforce_balance=False)
        root = mk_account(cur, account_type="asset", postable=False)
        current = mk_account(cur, account_type="asset", parent_id=root["id"], postable=False)
        leaf_a = mk_account(cur, account_type="asset", parent_id=current["id"])
        leaf_b = mk_account(cur, account_type="asset", parent_id=current["id"])
        mk_line(cur, mk_entry(cur, scen["id"]), leaf_a["id"], 300)
        mk_line(cur, mk_entry(cur, scen["id"]), leaf_b["id"], 200)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/balance-sheet?scenario={scen['code']}")
        assert r.status_code == 200
        assert _account_row_value(r.text, current["code"]) == "500.00"
        assert _account_row_value(r.text, root["code"]) == "500.00"


def test_journal_shows_back_to_report_link_for_a_safe_relative_target(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/entries?back=%2Ftrial-balance%3Fscenario%3DACTUAL")
        assert r.status_code == 200
        assert 'href="/trial-balance?scenario=ACTUAL">&larr; Back to report</a>' in r.text


def test_journal_drops_an_unsafe_back_target(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r1 = c.get("/entries?back=https://evil.example.com")
        assert "Back to report" not in r1.text
        r2 = c.get("/entries?back=//evil.example.com")
        assert "Back to report" not in r2.text


def test_trial_balance_and_balance_sheet_render_raw_as_a_plain_int(conn):
    # _trial_balance_rows/_balance_sheet_rows used to return their own
    # "raw": True/False (a Python bool) inside the result dict spread
    # into the template context *after* the route's own "raw": raw (the
    # real int query param) — the later key silently won, so every link
    # built from {{ raw }} rendered "raw=False"/"raw=True" instead of
    # "raw=0"/"raw=1" and 422'd the moment anything actually followed it
    # (Export CSV, the amount links' "back" URL, a Refresh resubmit).
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        for url in ("/trial-balance", "/balance-sheet"):
            r = c.get(url)
            assert r.status_code == 200
            assert "raw=False" not in r.text
            assert "raw=True" not in r.text
            assert "raw=0" in r.text


# ---------------------------------------------------------------------------
# Budget — income-statement-only scenarios (grid, not journal entries)
# ---------------------------------------------------------------------------
def test_create_scenario_income_statement_only_via_route(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post("/scenarios", data={
            "csrf_token": csrf_token, "code": "ISONLY1", "name": "Budget test",
            "scenario_type": "budget", "income_statement_only": "on",
        })
        assert "ok=" in r.headers["location"]
    with conn.cursor() as cur:
        cur.execute("SELECT income_statement_only FROM scenarios WHERE code = 'ISONLY1'")
        assert cur.fetchone()["income_statement_only"] is True


def test_income_statement_only_scenario_excluded_from_new_entry_panel(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, income_statement_only=True)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/entries?new=1")
        assert r.status_code == 200
        select_html = re.search(
            r'<select name="scenario_id" id="scenario">.*?</select>', r.text, re.S).group(0)
        assert f'value="{scen["id"]}"' not in select_html


def test_income_statement_only_scenario_excluded_from_scheduled_target(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, income_statement_only=True)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/scheduled")
        assert r.status_code == 200
        select_html = re.search(
            r'<select name="scenario_id" id="scenario">.*?</select>', r.text, re.S).group(0)
        assert f'value="{scen["id"]}"' not in select_html


def test_variance_page_excludes_income_statement_only_scenarios(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, income_statement_only=True)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get("/variance")
        assert r.status_code == 200
        assert f'value="{scen["code"]}"' not in r.text


def test_budget_page_shows_budgeted_actual_and_variance(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        cur.execute("SELECT id FROM scenarios WHERE code = 'ACTUAL'")
        actual_id = cur.fetchone()["id"]
        scen = mk_scenario(cur, income_statement_only=True)
        expense = mk_account(cur, account_type="expense")
        cash = mk_account(cur, account_type="asset")
        mk_budget_line(cur, scen["id"], expense["id"], 600, period_month="2026-08-01")
        cur.execute(
            """INSERT INTO journal_entries (scenario_id, entry_date, description)
               VALUES (%s, '2026-08-05', 'Test entry') RETURNING id""",
            (actual_id,))
        eid = cur.fetchone()["id"]
        mk_line(cur, eid, expense["id"], 450)
        mk_line(cur, eid, cash["id"], -450, line_no=2)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/budget?scenario={scen['code']}&month=2026-08")
        assert r.status_code == 200
        m = re.search(rf'data-account="{expense["code"]}"[^>]*value="([^"]*)"', r.text)
        assert m and m.group(1) == "600.00"
        assert _account_row_value(r.text, expense["code"]) == "450.00"  # Actual column
        assert "150.00" in r.text  # Variance = budgeted - actual = 600 - 450
        assert "25.0%" in r.text   # % variance = (600 - 450) / |600| * 100


def test_budget_page_rolls_up_a_subdivided_summary_account(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, income_statement_only=True)
        root = mk_account(cur, account_type="expense", postable=False)
        leaf_a = mk_account(cur, account_type="expense", parent_id=root["id"])
        leaf_b = mk_account(cur, account_type="expense", parent_id=root["id"])
        mk_budget_line(cur, scen["id"], leaf_a["id"], 300, period_month="2026-08-01")
        mk_budget_line(cur, scen["id"], leaf_b["id"], 200, period_month="2026-08-01")
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        r = c.get(f"/budget?scenario={scen['code']}&month=2026-08")
        assert r.status_code == 200
        m = re.search(rf'data-account="{leaf_a["code"]}"[^>]*value="([^"]*)"', r.text)
        assert m and m.group(1) == "300.00"
        # The summary row rolls up both leaves — plain text, not an input
        # (it isn't a postable account; there's nowhere for a budget_line
        # to attach to it).
        m2 = re.search(rf'data-id="{root["id"]}"[^>]*>.*?</tr>', r.text, re.S)
        assert m2 and "500.00" in m2.group(0)
        assert f'data-account="{root["code"]}"' not in r.text


def test_budget_cell_route_upserts(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, income_statement_only=True)
        acct = mk_account(cur, account_type="expense")
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r1 = c.post("/budget/cell", data={
            "csrf_token": csrf_token, "scenario_id": str(scen["id"]),
            "account": acct["code"], "period_month": "2026-08-01", "amount": "150",
        })
        assert r1.status_code == 200 and r1.json()["ok"] is True
        r2 = c.post("/budget/cell", data={
            "csrf_token": csrf_token, "scenario_id": str(scen["id"]),
            "account": acct["code"], "period_month": "2026-08-01", "amount": "175.50",
        })
        assert r2.status_code == 200 and r2.json()["ok"] is True
    with conn.cursor() as cur:
        cur.execute(
            "SELECT amount FROM budget_lines WHERE scenario_id = %s AND account_id = %s",
            (scen["id"], acct["id"]))
        rows = cur.fetchall()
        assert len(rows) == 1  # upsert, not a second row
        assert str(rows[0]["amount"]) == "175.50"


def test_budget_cell_route_rejects_unknown_account(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
        scen = mk_scenario(cur, income_statement_only=True)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        with conn.cursor() as cur:
            cur.execute("SELECT csrf_token FROM sessions WHERE token = %s",
                       (c.cookies["postwarden_session"],))
            csrf_token = cur.fetchone()["csrf_token"]
        r = c.post("/budget/cell", data={
            "csrf_token": csrf_token, "scenario_id": str(scen["id"]),
            "account": "NOPE999", "period_month": "2026-08-01", "amount": "10",
        })
        assert r.status_code == 400
        assert r.json()["ok"] is False


def test_report_filter_bars_load_auto_refresh(conn):
    # Every GET filter form auto-submits on a select/date/checkbox change
    # via one shared script — a regression guard that the script tag
    # itself is still wired into base.html, not that the JS behavior
    # works (that needs a real browser; see docs/ARCHITECTURE.md).
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        for url in ("/trial-balance", "/balance-sheet", "/income-statement",
                   "/variance", "/budget", "/entries"):
            r = c.get(url)
            assert r.status_code == 200
            assert 'auto-refresh.js' in r.text, url
        # A filter form whose fields wrap in a nested div (a second row
        # of checkboxes/Export CSV below them — see entries.html's own
        # comment on why) can't carry class="bar" itself without flexing
        # that div and the second row side by side — data-auto-refresh is
        # the same hook with no such layout side effect. Journal, Income
        # Statement, Variance, and Budget Grid all need it for exactly
        # this reason; its absence on the Journal specifically used to be
        # a real bug (Scenario/Account/Amount filters sitting inert while
        # every report's own filter bar already auto-submitted).
        for url in ("/entries", "/income-statement", "/variance", "/budget"):
            r = c.get(url)
            assert "data-auto-refresh" in r.text, url


def test_entry_grids_offer_a_distribute_button(conn):
    with conn.cursor() as cur:
        user = mk_user(cur)
    conn.commit()
    with TestClient(app, **client_kwargs) as c:
        c.post("/login", data={"username": user["username"], "password": user["password"]})
        for url in ("/entries?new=1", "/scheduled", "/templates"):
            r = c.get(url)
            assert r.status_code == 200
            assert 'id="distribute-row"' in r.text, url


def test_demo_banner_off_by_default(conn):
    """The default state every self-hoster gets: no banner, empty fields —
    POSTWARDEN_DEMO_MODE unset means demo_user/demo_password never even reach
    the page, regardless of whether POSTWARDEN_ADMIN_USER/PASSWORD are set."""
    with TestClient(app, **client_kwargs) as c:
        r = c.get("/login")
        assert r.status_code == 200
        assert "credentials prefilled in" not in r.text
        assert 'name="username" value="" required' in r.text
        assert 'name="password" value="" required' in r.text


def test_demo_banner_shows_and_prefills_credentials_when_enabled():
    """POSTWARDEN_DEMO_MODE is a second, explicit flag on top of
    POSTWARDEN_ADMIN_USER/PASSWORD, not implied by them being set — this is
    what actually keeps a normal self-hoster's own password off their own
    login page. Patches the Jinja globals directly (they're read once at
    import time from the environment, like VERSION) rather than the
    environment itself, since the app is already imported by the time any
    test runs."""
    originals = {k: templates.env.globals.get(k)
                for k in ("demo_banner", "demo_user", "demo_password")}
    templates.env.globals["demo_banner"] = True
    templates.env.globals["demo_user"] = "demo"
    templates.env.globals["demo_password"] = "s3cret"
    try:
        with TestClient(app, **client_kwargs) as c:
            r = c.get("/login")
            assert r.status_code == 200
            assert "credentials prefilled in" in r.text
            # The literal password appears as *readable text* in the callout,
            # not just silently dropped into the masked field — a visitor
            # who wants to reuse or share it later can actually read it.
            assert "s3cret" in r.text
            assert 'name="username" value="demo" required' in r.text
            assert 'name="password" value="s3cret" required' in r.text
    finally:
        for k, v in originals.items():
            templates.env.globals[k] = v

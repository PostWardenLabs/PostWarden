"""Libro — a personal general ledger with scenarios.

HTML screens for humans, /api/* JSON for machines, PostgreSQL for the truth.
"""
import calendar
import json
import re
import secrets
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode

import psycopg
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from . import auth
from .db import q, q1, tx


@asynccontextmanager
async def lifespan(app: FastAPI):
    auth.bootstrap_admin_from_env()
    yield


BASE = Path(__file__).parent
app = FastAPI(title="Libro", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

PUBLIC_PATHS = {"/login"}


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Every route needs a valid session except /login and static assets.
    Sets request.state.user once per request so handlers and templates
    (`request.state.user`) don't each need their own session lookup."""
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static/"):
        return await call_next(request)
    session = auth.get_session(request.cookies.get(auth.SESSION_COOKIE))
    if not session:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Not authenticated"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    request.state.user = session
    # No task runner in this deployment, so "auto-post on the date" is done
    # lazily here instead of on a real cron: cheap (an indexed SELECT that's
    # almost always empty) and each due schedule only ever materializes once
    # since materialize_due_schedules() advances next_date past today as
    # part of the same write. A failure here shouldn't take the app down.
    try:
        materialize_due_schedules()
    except Exception:
        pass
    return await call_next(request)


def money(v) -> Markup:
    """Renders as American-default text ("1,234.56", no symbol) so the page
    is correct even with JS disabled, but wraps it in a span carrying the
    plain numeric value — money-format.js rewrites every .money-fmt's
    displayed text from that raw value using whatever symbol/decimal/
    thousands preferences are saved in Settings (client-side only, same
    as the theme picker; the number stored in Postgres never changes)."""
    if v is None:
        return Markup("")
    return Markup(f'<span class="money-fmt" data-value="{v:.2f}">{v:,.2f}</span>')


def asset(filename: str) -> str:
    """Cache-busting URL for a static file: /static/x?v=<mtime>. Without a
    version query param, browsers can silently keep serving an old cached
    copy of app.js/style.css after a deploy — a plain reload isn't enough
    to guarantee a re-fetch. Appending the file's mtime changes the URL
    (and cache key) exactly when the file itself changes, no build step."""
    v = int((BASE / "static" / filename).stat().st_mtime)
    return f"/static/{filename}?v={v}"


def tojson(value) -> Markup:
    """Embed a value as JSON inside a <script type="application/json">
    block. Escapes <, >, & so a value containing e.g. "</script>" (account
    names are free text) can't break out of the tag; JSON.parse on the
    other end decodes the \\uXXXX escapes back to the real characters, so
    this only protects the HTML-embedding boundary — it says nothing about
    how the parsed value gets used afterwards. app.js only ever reads these
    parsed values via .textContent/.value (DOM APIs, never innerHTML), so
    there's no second escaping step needed there; keep it that way."""
    encoded = json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return Markup(encoded)


templates.env.filters["money"] = money
templates.env.filters["tojson"] = tojson
templates.env.globals["asset"] = asset

ACCOUNT_TYPES = ["asset", "liability", "equity", "income", "expense"]
TYPE_LABELS = {
    "asset": "Assets", "liability": "Liabilities", "equity": "Equity",
    "income": "Income", "expense": "Expenses",
}
SCENARIO_TYPES = ["actual", "budget", "forecast", "what_if"]


def scenarios_all():
    return q("""SELECT s.*, al.name AS base_level_name,
                       (SELECT COUNT(*) FROM journal_entries e
                         WHERE e.scenario_id = s.id) AS entry_count
                  FROM scenarios s
                  LEFT JOIN account_levels al ON al.id = s.base_level_id
                 ORDER BY s.scenario_type, s.code""")


def account_levels_all():
    return q("""SELECT al.*,
                       (SELECT COUNT(*) FROM scenarios s
                         WHERE s.base_level_id = al.id) AS scenario_count
                  FROM account_levels al ORDER BY al.depth""")


def postable_accounts_for_pickers():
    """Every account any scenario could actually post a line to: true
    leaves (always postable, any scenario), plus anything sitting exactly
    at a level some scenario has chosen as its base_level (see
    scenarios.base_level_id / fn_line_account_guard). The trigger is the
    real per-scenario enforcement; this just keeps a New entry/Scheduled/
    Template account picker from being needlessly narrow. A future
    refinement could filter this per the currently-selected scenario
    instead of showing the union of everything any scenario allows."""
    return q("""SELECT id, code, name, path FROM v_dim_account
                WHERE is_active AND (
                    is_postable
                    OR depth IN (SELECT al.depth FROM account_levels al
                                  JOIN scenarios s ON s.base_level_id = al.id)
                )
                ORDER BY sort_path""")


def flash_url(url: str, ok: str = None, err: str = None) -> str:
    params = {}
    if ok:
        params["ok"] = ok
    if err:
        params["err"] = err
    sep = "&" if "?" in url else "?"
    return url + (sep + urlencode(params) if params else "")


def flash_redirect(url: str, ok: str = None, err: str = None):
    return RedirectResponse(flash_url(url, ok, err), status_code=303)


def require_csrf(request: Request, token: str | None):
    """Raise ValueError (caught the same way as any other bad input) if the
    submitted token doesn't match this session's. Every state-changing POST
    calls this — see the hidden csrf_token field templates render from
    request.state.user.csrf_token."""
    user = auth.current_user(request)
    if not user or not token or not secrets.compare_digest(token, user["csrf_token"]):
        raise ValueError("Your session expired or the form was stale — please retry.")


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
@app.get("/login")
def login_page(request: Request, err: str = None):
    if auth.get_session(request.cookies.get(auth.SESSION_COOKIE)):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"err": err})


@app.post("/login")
def login_submit(username: str = Form(...), password: str = Form(...)):
    username = username.strip().lower()
    if auth.is_rate_limited(username):
        return flash_redirect(
            "/login", err="Too many failed attempts — wait a few minutes and try again")
    row = q1("SELECT id, password_hash, is_active FROM users WHERE username = %s",
             (username,))
    if not row or not row["is_active"] or not auth.verify_password(password, row["password_hash"]):
        auth.record_failed_login(username)
        return flash_redirect("/login", err="Invalid username or password")
    auth.clear_failed_logins(username)
    token = auth.create_session(row["id"])
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(auth.SESSION_COOKIE, token, httponly=True, samesite="lax",
                    secure=auth.COOKIE_SECURE, max_age=int(auth.SESSION_TTL.total_seconds()))
    return resp


@app.post("/logout")
def logout(request: Request, csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
    except ValueError:
        pass  # worst case of a bad token here is a no-op logout; just proceed
    user = auth.current_user(request)
    if user:
        auth.delete_session(user["token"])
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


# ---------------------------------------------------------------------------
# User settings — username/password, and the theme picker (see settings.html)
# ---------------------------------------------------------------------------
USERNAME_PATTERN = re.compile(r"^[a-z0-9_.-]{3,32}$")


@app.get("/settings")
def settings_page(request: Request, ok: str = None, err: str = None):
    return templates.TemplateResponse(request, "settings.html", {
        "nav": "settings", "ok": ok, "err": err,
    })


@app.post("/settings/username")
def change_username(request: Request, username: str = Form(...),
                    csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        username = username.strip().lower()
        if not USERNAME_PATTERN.match(username):
            raise ValueError(
                "Username must be 3-32 characters: lowercase letters, numbers, "
                "_ . or - only")
        user_id = auth.current_user(request)["user_id"]
        with tx() as cur:
            cur.execute("UPDATE users SET username = %s WHERE id = %s",
                       (username, user_id))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/settings", err=msg)
    return flash_redirect("/settings", ok=f"Username changed to {username!r}")


@app.post("/settings/password")
def change_password(request: Request, current_password: str = Form(...),
                    new_password: str = Form(...), confirm_password: str = Form(...),
                    csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        session = auth.current_user(request)
        row = q1("SELECT password_hash FROM users WHERE id = %s", (session["user_id"],))
        if not row or not auth.verify_password(current_password, row["password_hash"]):
            raise ValueError("Current password is incorrect")
        if new_password != confirm_password:
            raise ValueError("New password and confirmation don't match")
        if len(new_password) < 8:
            raise ValueError("New password must be at least 8 characters")
        with tx() as cur:
            cur.execute("UPDATE users SET password_hash = %s WHERE id = %s",
                       (auth.hash_password(new_password), session["user_id"]))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/settings", err=msg)
    # Same as the CLI's reset-password: revoke every session for this user,
    # including the current one — logging back in with the new password is
    # itself the confirmation that it was set correctly.
    auth.delete_all_sessions_for_user(session["user_id"])
    resp = flash_redirect("/login", ok="Password changed — please log in again")
    resp.delete_cookie(auth.SESSION_COOKIE)
    return resp


# ---------------------------------------------------------------------------
# Trial balance
# ---------------------------------------------------------------------------
@app.get("/")
def trial_balance(request: Request, scenario: str = "ACTUAL",
                  as_of: str = None, zeros: int = 0):
    as_of_date = as_of or None
    rows = q("SELECT * FROM fn_trial_balance(%s, %s)", (scenario, as_of_date))
    if not zeros:
        rows = [r for r in rows if r["net"] != 0]

    grouped = []
    for t in ACCOUNT_TYPES:
        sub = [r for r in rows if r["acct_type"] == t]
        if sub:
            grouped.append({
                "type": t, "label": TYPE_LABELS[t], "rows": sub,
                "sub_debits": sum(r["debit_balance"] for r in sub),
                "sub_credits": sum(r["credit_balance"] for r in sub),
            })

    total_debits = sum(r["debit_balance"] for r in rows)
    total_credits = sum(r["credit_balance"] for r in rows)
    return templates.TemplateResponse(request, "trial_balance.html", {
        "nav": "tb", "grouped": grouped, "scenario": scenario,
        "as_of": as_of or "", "zeros": zeros,
        "scenarios": scenarios_all(),
        "total_debits": total_debits, "total_credits": total_credits,
        "in_balance": total_debits == total_credits,
        "today": date.today().isoformat(),
    })


# ---------------------------------------------------------------------------
# Variance — budget (or any scenario) vs. actual (or any other scenario),
# rolled up to a common level so a coarse scenario (posted straight to
# "Bank") lines up against a fine one (Checking + Savings) instead of
# just not matching up at all.
# ---------------------------------------------------------------------------
@app.get("/variance")
def variance_page(request: Request, baseline: str = "ACTUAL", compare: str = "",
                  level_id: str = "", as_of: str = None):
    scens = scenarios_all()
    codes = [s["code"] for s in scens]
    if not compare:
        others = [s["code"] for s in scens if s["code"] != baseline]
        compare = others[0] if others else ""

    level_depth = None
    if level_id:
        lvl = q1("SELECT depth FROM account_levels WHERE id = %s", (int(level_id),))
        level_depth = lvl["depth"] if lvl else None
    elif compare:
        # Default to the comparison scenario's own base level, if it has
        # one — the natural granularity it was actually entered at. Set
        # level_id too (not just level_depth) so the picker reflects what
        # was actually used instead of silently showing "no rollup".
        bl = q1("""SELECT al.id, al.depth FROM scenarios s
                    JOIN account_levels al ON al.id = s.base_level_id
                   WHERE s.code = %s""", (compare,))
        if bl:
            level_depth = bl["depth"]
            level_id = str(bl["id"])

    as_of_date = as_of or None
    baseline_rows = {r["account_id"]: r for r in q(
        "SELECT * FROM fn_rollup_balance(%s, %s, %s)",
        (baseline, level_depth, as_of_date))} if baseline in codes else {}
    compare_rows = {r["account_id"]: r for r in q(
        "SELECT * FROM fn_rollup_balance(%s, %s, %s)",
        (compare, level_depth, as_of_date))} if compare in codes else {}

    merged = []
    for aid in set(baseline_rows) | set(compare_rows):
        b = baseline_rows.get(aid)
        c = compare_rows.get(aid)
        ref = b or c
        b_net = b["net"] if b else 0
        c_net = c["net"] if c else 0
        merged.append({
            "account_code": ref["account_code"], "account_name": ref["account_name"],
            "path": ref["path"], "sort_path": ref["sort_path"], "acct_type": ref["acct_type"],
            "baseline_net": b_net, "compare_net": c_net, "variance": c_net - b_net,
        })

    grouped = []
    for t in ACCOUNT_TYPES:
        sub = sorted((r for r in merged if r["acct_type"] == t), key=lambda r: r["sort_path"])
        if sub:
            grouped.append({
                "type": t, "label": TYPE_LABELS[t], "rows": sub,
                "sub_baseline": sum(r["baseline_net"] for r in sub),
                "sub_compare": sum(r["compare_net"] for r in sub),
                "sub_variance": sum(r["variance"] for r in sub),
            })

    return templates.TemplateResponse(request, "variance.html", {
        "nav": "variance", "grouped": grouped, "scenarios": scens,
        "levels": account_levels_all(), "baseline": baseline, "compare": compare,
        "level_id": level_id, "as_of": as_of or "",
        "total_baseline": sum(r["baseline_net"] for r in merged),
        "total_compare": sum(r["compare_net"] for r in merged),
        "total_variance": sum(r["variance"] for r in merged),
        "today": date.today().isoformat(),
    })


# ---------------------------------------------------------------------------
# Chart of accounts
# ---------------------------------------------------------------------------
# Seed.sql's own convention (1xxx assets, 2xxx liabilities, ...) isn't
# DB-enforced, just a habit — quick-created accounts follow it anyway so
# the chart stays legible without asking the user to think about codes.
ACCOUNT_TYPE_CODE_PREFIX = {
    "asset": "1", "liability": "2", "equity": "3", "income": "4", "expense": "5",
}


def _next_account_code(account_type: str) -> str:
    prefix = ACCOUNT_TYPE_CODE_PREFIX[account_type]
    existing = {int(r["code"]) for r in q(
        "SELECT code FROM accounts WHERE code LIKE %s", (prefix + "%",))}
    candidate = (max(existing) + 10) if existing else int(prefix + "000")
    while candidate in existing:
        candidate += 1
    return str(candidate)


def _accounts_with_gaps(accounts: list[dict]) -> list[dict]:
    """Interleaves a "gap" placeholder before every account row (and one
    trailing) so accounts.html can render an Actual Budget-style "+" for
    adding a category between any two adjacent rows, instead of only via
    the form at the bottom.

    Deliberately does NOT decide each gap's parent_id/account_type here —
    which two rows are visually adjacent around a given gap depends on
    which summary accounts are currently collapsed, and that's a client-
    side (localStorage) preference this request has no way to see. Each
    gap just needs to know which account row to track for visibility
    (see accounts.js); accounts.js computes the actual parent/type at
    "+"-click time from whichever rows are visible right then."""
    out = []
    prev = None
    for acct in accounts:
        out.append({"kind": "gap", "track_id": acct["id"]})
        out.append({"kind": "account", **acct})
        prev = acct
    out.append({"kind": "gap", "track_id": prev["id"] if prev else None})
    return out


@app.get("/accounts")
def accounts_page(request: Request, level_id: str = "", ok: str = None, err: str = None):
    accounts = q("SELECT * FROM v_dim_account ORDER BY sort_path")
    selected_level = q1("SELECT * FROM account_levels WHERE id = %s",
                        (int(level_id),)) if level_id else None
    if selected_level:
        display_accounts = [a for a in accounts if a["depth"] == selected_level["depth"]]
        rows = None
    else:
        display_accounts = accounts
        rows = _accounts_with_gaps(accounts)
    return templates.TemplateResponse(request, "accounts.html", {
        "nav": "accounts", "accounts": accounts, "rows": rows,
        "display_accounts": display_accounts,
        "levels": account_levels_all(), "selected_level": selected_level,
        "account_types": ACCOUNT_TYPES, "type_labels": TYPE_LABELS,
        "ok": ok, "err": err,
    })


@app.post("/accounts")
def create_account(request: Request, code: str = Form(...), name: str = Form(...),
                   account_type: str = Form(...), parent_id: str = Form(""),
                   is_postable: str = Form(None), csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        with tx() as cur:
            cur.execute(
                """INSERT INTO accounts (code, name, account_type, parent_id, is_postable)
                   VALUES (%s, %s, %s, %s, %s)""",
                (code.strip(), name.strip(), account_type,
                 int(parent_id) if parent_id else None,
                 is_postable is not None),
            )
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/accounts", err=msg)
    return flash_redirect("/accounts", ok=f"Account {code} — {name} created")


@app.post("/accounts/quick-create")
def quick_create_account(request: Request, name: str = Form(...),
                         parent_id: str = Form(""), account_type: str = Form(""),
                         is_postable: str = Form(None), csrf_token: str = Form(...)):
    # Powers the "+" between two rows on /accounts (see accounts.js) — the
    # code is generated, not typed, same spirit as Actual Budget's category
    # picker not showing account numbers at all; /accounts's own bottom
    # form is still there for anyone who wants to set an exact code.
    try:
        require_csrf(request, csrf_token)
        name = name.strip()
        if not name:
            raise ValueError("Name is required")
        pid = int(parent_id) if parent_id else None
        if pid:
            parent = q1("SELECT account_type FROM accounts WHERE id = %s", (pid,))
            if not parent:
                raise ValueError("Unknown parent account")
            acct_type = parent["account_type"]
        else:
            acct_type = account_type
            if acct_type not in ACCOUNT_TYPES:
                raise ValueError("Choose an account type")
        code = _next_account_code(acct_type)
        with tx() as cur:
            cur.execute(
                """INSERT INTO accounts (code, name, account_type, parent_id, is_postable)
                   VALUES (%s, %s, %s, %s, %s)""",
                (code, name, acct_type, pid, is_postable is not None))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/accounts", err=msg)
    return flash_redirect("/accounts", ok=f"Account {code} — {name} created")


@app.post("/accounts/{account_id}/toggle-active")
def toggle_account(account_id: int, request: Request, csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        with tx() as cur:
            cur.execute(
                "UPDATE accounts SET is_active = NOT is_active WHERE id = %s",
                (account_id,))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/accounts", err=msg)
    return flash_redirect("/accounts", ok="Account updated")


# ---------------------------------------------------------------------------
# Journal entry — the keyboard-first screen
# ---------------------------------------------------------------------------
@app.get("/entries/new")
def entry_new(request: Request, err: str = None):
    postable = postable_accounts_for_pickers()
    scen = [s for s in scenarios_all() if not s["is_locked"]]
    active_payees = q("SELECT id, name FROM payees WHERE is_active ORDER BY name")
    return templates.TemplateResponse(request, "entry_new.html", {
        "nav": "new", "accounts": postable, "scenarios": scen,
        "payees": active_payees, "tpls": templates_full(),
        "today": date.today().isoformat(), "err": err, "all_tags": all_tags(),
    })


TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9 _-]{0,39}$")


def all_tags() -> list[str]:
    return [r["name"] for r in q("SELECT name FROM tags ORDER BY name")]


def _parse_tags(raw: str) -> list[str]:
    """Comma-separated tag names from the tag-input widget (see tags.js) ->
    a clean, deduped, validated list — matches tags.name's CHECK constraint
    so a bad tag fails here with a plain message instead of a raw
    constraint-violation error."""
    seen = []
    for piece in (raw or "").split(","):
        name = piece.strip().lower()
        if not name or name in seen:
            continue
        if not TAG_PATTERN.match(name):
            raise ValueError(
                f"Invalid tag {name!r}: letters, numbers, spaces, - and _ only, max 40 chars")
        seen.append(name)
    return seen


def _sync_tags(cur, table: str, id_col: str, obj_id: int, tag_names: list[str]) -> None:
    """Shared by journal entries and scheduled entries — both have their own
    entry_id/tag_id junction table with the same shape."""
    cur.execute(f"DELETE FROM {table} WHERE {id_col} = %s", (obj_id,))
    for name in tag_names:
        cur.execute(
            """INSERT INTO tags (name) VALUES (%s)
               ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
               RETURNING id""",
            (name,))
        tag_id = cur.fetchone()["id"]
        cur.execute(
            f"INSERT INTO {table} ({id_col}, tag_id) VALUES (%s, %s)",
            (obj_id, tag_id))


def _sync_entry_tags(cur, entry_id: int, tag_names: list[str]) -> None:
    _sync_tags(cur, "journal_entry_tags", "entry_id", entry_id, tag_names)


def _parse_lines(form) -> list[dict]:
    """Turn parallel account[]/debit[]/credit[]/memo[] arrays into line dicts.

    Rules mirror the paper form: a line needs an account and exactly one of
    debit or credit, strictly positive. Blank rows are ignored. The account
    field is a <select> (searchable combobox in the UI — see app.js), so
    its value is already a bare code; no "code · name" text to split here
    the way a free-text field would need — this is just defense in depth
    against a client that isn't the browser UI.
    """
    accounts = form.getlist("account")
    debits = form.getlist("debit")
    credits = form.getlist("credit")
    memos = form.getlist("memo")
    lines = []
    for i, acct in enumerate(accounts):
        code = (acct or "").strip()
        d = (debits[i] if i < len(debits) else "").strip()
        c = (credits[i] if i < len(credits) else "").strip()
        memo = (memos[i] if i < len(memos) else "").strip() or None
        if not code and not d and not c:
            continue  # blank row
        if not code:
            raise ValueError(f"Line {i + 1}: missing account")
        dv = float(d) if d else 0.0
        cv = float(c) if c else 0.0
        if dv < 0 or cv < 0:
            raise ValueError(f"Line {i + 1}: amounts must be positive")
        if (dv > 0) == (cv > 0):
            raise ValueError(
                f"Line {i + 1}: enter exactly one of debit or credit")
        lines.append({"code": code, "amount": round(dv - cv, 2), "memo": memo})
    if not lines:
        raise ValueError("The entry has no lines")
    return lines


@app.post("/entries")
async def create_entry(request: Request):
    form = await request.form()
    # The entry-grid page submits via fetch() so a rejected entry (e.g. a
    # bad account code) doesn't lose the lines the user already typed —
    # it asks for JSON back instead of a redirect. See app.js.
    wants_json = "application/json" in request.headers.get("accept", "")
    try:
        require_csrf(request, form.get("csrf_token"))
        lines = _parse_lines(form)
        entry_date = form.get("entry_date") or date.today().isoformat()
        scenario_id = int(form.get("scenario_id"))
        description = (form.get("description") or "").strip()
        reference = (form.get("reference") or "").strip() or None
        tag_names = _parse_tags(form.get("tags", ""))
        payee_id = int(form.get("payee_id")) if form.get("payee_id") else None
        if not description:
            raise ValueError("Description is required")

        codes = {ln["code"] for ln in lines}
        found = {r["code"] for r in q(
            "SELECT code FROM accounts WHERE code = ANY(%s)", (list(codes),))}
        missing = codes - found
        if missing:
            raise ValueError(f"Unknown account code: {', '.join(sorted(missing))}")

        with tx() as cur:
            cur.execute(
                """INSERT INTO journal_entries
                       (scenario_id, entry_date, description, reference,
                        payee_id, created_by_user_id)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (scenario_id, entry_date, description, reference, payee_id,
                 auth.current_user(request)["user_id"]))
            entry_id = cur.fetchone()["id"]
            for n, ln in enumerate(lines, start=1):
                cur.execute(
                    """INSERT INTO journal_lines
                           (entry_id, line_no, account_id, amount, memo)
                       VALUES (%s, %s,
                               (SELECT id FROM accounts WHERE code = %s),
                               %s, %s)""",
                    (entry_id, n, ln["code"], ln["amount"], ln["memo"]))
            if tag_names:
                _sync_entry_tags(cur, entry_id, tag_names)
        # the deferred trigger has now blessed the entry at COMMIT
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        if wants_json:
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        return flash_redirect("/entries/new", err=msg)
    ok_msg = f"Entry #{entry_id} posted"
    if wants_json:
        return JSONResponse({"ok": True, "redirect": flash_url("/entries", ok=ok_msg)})
    return flash_redirect("/entries", ok=ok_msg)


# ---------------------------------------------------------------------------
# Journal browser
# ---------------------------------------------------------------------------
@app.get("/entries")
def entries_page(request: Request, scenario: str = "", date_from: str = "",
                 date_to: str = "", qtext: str = "", tags: str = "",
                 ok: str = None, err: str = None):
    try:
        tag_list = _parse_tags(tags) if tags else []
    except ValueError:
        tag_list = []  # a hand-edited URL with a malformed tag; just ignore it
    where, params = ["TRUE"], []
    if scenario:
        where.append("s.code = %s")
        params.append(scenario)
    if date_from:
        where.append("e.entry_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("e.entry_date <= %s")
        params.append(date_to)
    if qtext:
        where.append("(e.description ILIKE %s OR e.reference ILIKE %s)")
        params.extend([f"%{qtext}%", f"%{qtext}%"])
    if tag_list:
        # ANY of the given tags — a broadening filter, like most tag UIs.
        where.append("""e.id IN (SELECT jet.entry_id FROM journal_entry_tags jet
                                   JOIN tags tg ON tg.id = jet.tag_id
                                  WHERE tg.name = ANY(%s))""")
        params.append(tag_list)

    entries = q(f"""
        SELECT e.id, e.entry_date, e.description, e.reference,
               e.reverses_entry_id, s.code AS scenario_code,
               s.is_locked AS scenario_locked, u.username AS posted_by,
               p.name AS payee_name,
               (SELECT COALESCE(SUM(l.debit), 0) FROM journal_lines l
                 WHERE l.entry_id = e.id) AS total_debits,
               (SELECT COALESCE(SUM(l.credit), 0) FROM journal_lines l
                 WHERE l.entry_id = e.id) AS total_credits,
               (SELECT r.id FROM journal_entries r
                 WHERE r.reverses_entry_id = e.id LIMIT 1) AS reversed_by
          FROM journal_entries e
          JOIN scenarios s ON s.id = e.scenario_id
          LEFT JOIN users u ON u.id = e.created_by_user_id
          LEFT JOIN payees p ON p.id = e.payee_id
         WHERE {' AND '.join(where)}
         ORDER BY e.entry_date DESC, e.id DESC
         LIMIT 200""", params)

    ids = [e["id"] for e in entries]
    lines_by_entry = {}
    tags_by_entry = {}
    if ids:
        for ln in q("""SELECT l.entry_id, l.line_no, l.debit, l.credit,
                              l.memo, a.code AS account_code,
                              a.name AS account_name
                         FROM journal_lines l
                         JOIN accounts a ON a.id = l.account_id
                        WHERE l.entry_id = ANY(%s)
                        ORDER BY l.entry_id, l.line_no""", (ids,)):
            lines_by_entry.setdefault(ln["entry_id"], []).append(ln)
        for tg in q("""SELECT jet.entry_id, tg.name
                         FROM journal_entry_tags jet
                         JOIN tags tg ON tg.id = jet.tag_id
                        WHERE jet.entry_id = ANY(%s)
                        ORDER BY tg.name""", (ids,)):
            tags_by_entry.setdefault(tg["entry_id"], []).append(tg["name"])

    return templates.TemplateResponse(request, "entries.html", {
        "nav": "entries", "entries": entries, "lines_by_entry": lines_by_entry,
        "tags_by_entry": tags_by_entry, "tags": tags, "all_tags": all_tags(),
        "scenarios": scenarios_all(), "scenario": scenario,
        "date_from": date_from, "date_to": date_to, "qtext": qtext,
        "ok": ok, "err": err,
    })


@app.post("/entries/{entry_id}/reverse")
def reverse_entry(entry_id: int, request: Request, csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        orig = q1("""SELECT e.*, s.code AS scenario_code FROM journal_entries e
                     JOIN scenarios s ON s.id = e.scenario_id
                     WHERE e.id = %s""", (entry_id,))
        if not orig:
            return flash_redirect("/entries", err=f"Entry #{entry_id} not found")
        already = q1("SELECT id FROM journal_entries WHERE reverses_entry_id = %s",
                     (entry_id,))
        if already:
            return flash_redirect(
                "/entries",
                err=f"Entry #{entry_id} was already reversed by #{already['id']}")
        with tx() as cur:
            cur.execute(
                """INSERT INTO journal_entries
                       (scenario_id, entry_date, description, reference,
                        reverses_entry_id, payee_id, created_by_user_id)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (orig["scenario_id"], date.today(),
                 f"Reversal of #{entry_id} — {orig['description']}",
                 orig["reference"], entry_id, orig["payee_id"],
                 auth.current_user(request)["user_id"]))
            new_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO journal_lines
                       (entry_id, line_no, account_id, amount, memo)
                   SELECT %s, line_no, account_id, -amount, memo
                     FROM journal_lines WHERE entry_id = %s""",
                (new_id, entry_id))
            # Carry the original's tags over — a reversal is still "about"
            # whatever it was tagged for.
            cur.execute(
                """INSERT INTO journal_entry_tags (entry_id, tag_id)
                   SELECT %s, tag_id FROM journal_entry_tags WHERE entry_id = %s""",
                (new_id, entry_id))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/entries", err=msg)
    return flash_redirect("/entries",
                          ok=f"Entry #{entry_id} reversed by #{new_id}")


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
@app.get("/scenarios")
def scenarios_page(request: Request, ok: str = None, err: str = None):
    return templates.TemplateResponse(request, "scenarios.html", {
        "nav": "scenarios", "scenarios": scenarios_all(),
        "levels": account_levels_all(),
        "scenario_types": SCENARIO_TYPES, "ok": ok, "err": err,
    })


@app.post("/scenarios")
def create_scenario(request: Request, code: str = Form(...), name: str = Form(...),
                    scenario_type: str = Form(...),
                    enforce_balance: str = Form(None),
                    base_level_id: str = Form(""),
                    notes: str = Form(""), csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        with tx() as cur:
            cur.execute(
                """INSERT INTO scenarios
                       (code, name, scenario_type, enforce_balance, base_level_id, notes)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (code.strip().upper(), name.strip(), scenario_type,
                 enforce_balance is not None,
                 int(base_level_id) if base_level_id else None,
                 notes.strip() or None))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/scenarios", err=msg)
    return flash_redirect("/scenarios", ok=f"Scenario {code.upper()} created")


@app.post("/scenarios/{scenario_id}/toggle-lock")
def toggle_lock(scenario_id: int, request: Request, csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        with tx() as cur:
            cur.execute(
                "UPDATE scenarios SET is_locked = NOT is_locked WHERE id = %s",
                (scenario_id,))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/scenarios", err=msg)
    return flash_redirect("/scenarios", ok="Scenario updated")


# ---------------------------------------------------------------------------
# Account levels — user-named steps down the chart of accounts (see
# account_levels/scenarios.base_level_id in db/schema.sql). A scenario
# picks one of these as its base_level to post at a whole branch instead
# of every leaf under it — vertical extensibility, OneStream-style.
# ---------------------------------------------------------------------------
@app.get("/account-levels")
def account_levels_page(request: Request, ok: str = None, err: str = None):
    levels = account_levels_all()
    next_depth = max((lv["depth"] for lv in levels), default=0) + 1
    return templates.TemplateResponse(request, "account_levels.html", {
        "nav": "account_levels", "levels": levels, "next_depth": next_depth,
        "ok": ok, "err": err,
    })


@app.post("/account-levels")
def create_account_level(request: Request, name: str = Form(...), depth: str = Form(...),
                         csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        name = name.strip()
        if not name:
            raise ValueError("Name is required")
        depth_i = int(depth)
        if depth_i <= 0:
            raise ValueError("Depth must be a positive number")
        with tx() as cur:
            cur.execute(
                "INSERT INTO account_levels (name, depth) VALUES (%s, %s)",
                (name, depth_i))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/account-levels", err=msg)
    return flash_redirect("/account-levels", ok=f"Level {name!r} created")


@app.post("/account-levels/{level_id}/rename")
def rename_account_level(level_id: int, request: Request, name: str = Form(...),
                         csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        name = name.strip()
        if not name:
            raise ValueError("Name is required")
        with tx() as cur:
            cur.execute("UPDATE account_levels SET name = %s WHERE id = %s",
                       (name, level_id))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/account-levels", err=msg)
    return flash_redirect("/account-levels", ok="Level renamed")


@app.post("/account-levels/{level_id}/delete")
def delete_account_level(level_id: int, request: Request, csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        with tx() as cur:
            cur.execute("DELETE FROM account_levels WHERE id = %s", (level_id,))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/account-levels", err=msg)
    return flash_redirect("/account-levels", ok="Level deleted")


# ---------------------------------------------------------------------------
# Payees
# ---------------------------------------------------------------------------
def payees_all():
    return q("""SELECT p.*, (SELECT COUNT(*) FROM journal_entries e
                             WHERE e.payee_id = p.id) AS entry_count
                FROM payees p ORDER BY p.name""")


@app.get("/payees")
def payees_page(request: Request, ok: str = None, err: str = None):
    return templates.TemplateResponse(request, "payees.html", {
        "nav": "payees", "payees": payees_all(), "ok": ok, "err": err,
    })


@app.post("/payees")
def create_payee(request: Request, name: str = Form(...), csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        name = name.strip()
        if not name:
            raise ValueError("Payee name is required")
        with tx() as cur:
            cur.execute("INSERT INTO payees (name) VALUES (%s)", (name,))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/payees", err=msg)
    return flash_redirect("/payees", ok=f"Payee {name!r} created")


@app.post("/payees/quick-create")
def quick_create_payee(request: Request, name: str = Form(...), csrf_token: str = Form(...)):
    # Called from the payee combobox on New entry via fetch() — "+ Create
    # <name>" there needs a real row back immediately so the <select> has
    # something to point payee_id at, unlike tags (synced by name at
    # submit time) or the /payees form (which redirects a whole page).
    # ON CONFLICT DO UPDATE (a no-op update) rather than DO NOTHING is the
    # standard trick to get RETURNING even when the name already exists —
    # it also quietly reactivates a deactivated payee the user is now
    # using again, which is what typing its name here signals.
    try:
        require_csrf(request, csrf_token)
        name = name.strip()
        if not name:
            raise ValueError("Payee name is required")
        with tx() as cur:
            cur.execute(
                """INSERT INTO payees (name) VALUES (%s)
                   ON CONFLICT (name) DO UPDATE
                       SET is_active = TRUE
                   RETURNING id, name""",
                (name,))
            row = cur.fetchone()
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return JSONResponse({"ok": True, "id": row["id"], "name": row["name"]})


@app.post("/payees/{payee_id}/toggle-active")
def toggle_payee(payee_id: int, request: Request, csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        with tx() as cur:
            cur.execute(
                "UPDATE payees SET is_active = NOT is_active WHERE id = %s",
                (payee_id,))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/payees", err=msg)
    return flash_redirect("/payees", ok="Payee updated")


# ---------------------------------------------------------------------------
# Scheduled entries — a template + recurrence rule. Due occurrences are
# auto-posted to the Staging scenario (materialize_due_schedules(), called
# from the auth middleware); a human approves each one from here before it
# becomes a real entry in its target scenario ("posting" = copy + mark the
# staging row promoted, never editing it in place — same append-only spirit
# as the rest of the ledger).
# ---------------------------------------------------------------------------
SCHEDULE_UNITS = ["day", "week", "month"]


def _advance_date(d: date, unit: str, count: int) -> date:
    if unit == "day":
        return d + timedelta(days=count)
    if unit == "week":
        return d + timedelta(weeks=count)
    if unit == "month":
        total = d.month - 1 + count
        year = d.year + total // 12
        month = total % 12 + 1
        day = min(d.day, calendar.monthrange(year, month)[1])  # clamp Jan 31 + 1mo -> Feb 28/29
        return date(year, month, day)
    raise ValueError(f"Unknown interval unit: {unit}")


def scheduled_all():
    return q("""
        SELECT se.*, s.code AS scenario_code, s.name AS scenario_name,
               p.name AS payee_name,
               (SELECT COUNT(*) FROM scheduled_entry_lines
                 WHERE scheduled_entry_id = se.id) AS line_count,
               (SELECT COALESCE(SUM(debit), 0) FROM scheduled_entry_lines
                 WHERE scheduled_entry_id = se.id) AS total_amount
          FROM scheduled_entries se
          JOIN scenarios s ON s.id = se.target_scenario_id
          LEFT JOIN payees p ON p.id = se.payee_id
         ORDER BY se.next_date, se.id""")


def pending_scheduled_entries():
    """Staging entries materialized from a schedule but not yet approved —
    the admin page's whole reason to have a "Post" button."""
    entries = q("""
        SELECT e.id, e.entry_date, e.description, e.reference,
               p.name AS payee_name,
               ts.code AS target_scenario_code, ts.name AS target_scenario_name,
               (SELECT COALESCE(SUM(l.debit), 0) FROM journal_lines l
                 WHERE l.entry_id = e.id) AS total_debits
          FROM journal_entries e
          JOIN scheduled_entries se ON se.id = e.scheduled_entry_id
          JOIN scenarios ts ON ts.id = se.target_scenario_id
          LEFT JOIN payees p ON p.id = e.payee_id
         WHERE e.promoted_entry_id IS NULL
         ORDER BY e.entry_date, e.id""")
    ids = [e["id"] for e in entries]
    lines_by_entry = {}
    if ids:
        for ln in q("""SELECT l.entry_id, l.debit, l.credit, l.memo,
                              a.code AS account_code, a.name AS account_name
                         FROM journal_lines l
                         JOIN accounts a ON a.id = l.account_id
                        WHERE l.entry_id = ANY(%s)
                        ORDER BY l.entry_id, l.line_no""", (ids,)):
            lines_by_entry.setdefault(ln["entry_id"], []).append(ln)
    return entries, lines_by_entry


def materialize_due_schedules() -> None:
    due = q("""SELECT * FROM scheduled_entries
               WHERE is_active AND next_date <= CURRENT_DATE
               ORDER BY id""")
    if not due:
        return
    staging = q1("SELECT id FROM scenarios WHERE code = 'STAGING'")
    if not staging:
        return  # schema migrated but the seed row hasn't landed yet
    for sched in due:
        lines = q("""SELECT line_no, account_id, amount, memo
                       FROM scheduled_entry_lines
                      WHERE scheduled_entry_id = %s ORDER BY line_no""", (sched["id"],))
        if not lines:
            continue  # nothing to post; leave next_date alone rather than skip silently
        tag_names = [r["name"] for r in q(
            """SELECT tg.name FROM scheduled_entry_tags st
                JOIN tags tg ON tg.id = st.tag_id
               WHERE st.scheduled_entry_id = %s""", (sched["id"],))]
        with tx() as cur:
            cur.execute(
                """INSERT INTO journal_entries
                       (scenario_id, entry_date, description, reference,
                        payee_id, scheduled_entry_id)
                   VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                (staging["id"], sched["next_date"], sched["description"],
                 sched["reference"], sched["payee_id"], sched["id"]))
            entry_id = cur.fetchone()["id"]
            for ln in lines:
                cur.execute(
                    """INSERT INTO journal_lines
                           (entry_id, line_no, account_id, amount, memo)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (entry_id, ln["line_no"], ln["account_id"], ln["amount"], ln["memo"]))
            if tag_names:
                _sync_entry_tags(cur, entry_id, tag_names)
            cur.execute(
                "UPDATE scheduled_entries SET next_date = %s WHERE id = %s",
                (_advance_date(sched["next_date"], sched["interval_unit"],
                               sched["interval_count"]), sched["id"]))


@app.get("/scheduled")
def scheduled_page(request: Request, ok: str = None, err: str = None):
    postable = postable_accounts_for_pickers()
    scen = [s for s in scenarios_all() if not s["is_locked"]]
    active_payees = q("SELECT id, name FROM payees WHERE is_active ORDER BY name")
    pending, pending_lines = pending_scheduled_entries()
    return templates.TemplateResponse(request, "scheduled.html", {
        "nav": "scheduled", "schedules": scheduled_all(),
        "accounts": postable, "scenarios": scen, "payees": active_payees,
        "all_tags": all_tags(), "today": date.today().isoformat(),
        "units": SCHEDULE_UNITS,
        "pending": pending, "pending_lines": pending_lines,
        "ok": ok, "err": err,
    })


@app.post("/scheduled")
async def create_schedule(request: Request):
    form = await request.form()
    wants_json = "application/json" in request.headers.get("accept", "")
    try:
        require_csrf(request, form.get("csrf_token"))
        lines = _parse_lines(form)
        total = round(sum(ln["amount"] for ln in lines), 2)
        if total != 0:
            raise ValueError("Schedule lines must balance (debits = credits)")
        description = (form.get("description") or "").strip()
        if not description:
            raise ValueError("Description is required")
        reference = (form.get("reference") or "").strip() or None
        payee_id = int(form.get("payee_id")) if form.get("payee_id") else None
        tag_names = _parse_tags(form.get("tags", ""))
        target_scenario_id = int(form.get("scenario_id"))
        interval_unit = form.get("interval_unit") or ""
        if interval_unit not in SCHEDULE_UNITS:
            raise ValueError("Choose a valid repeat unit")
        interval_count = int(form.get("interval_count") or 1)
        if interval_count <= 0:
            raise ValueError("Repeat count must be positive")
        next_date = form.get("next_date") or date.today().isoformat()

        codes = {ln["code"] for ln in lines}
        found = {r["code"] for r in q(
            "SELECT code FROM accounts WHERE code = ANY(%s)", (list(codes),))}
        missing = codes - found
        if missing:
            raise ValueError(f"Unknown account code: {', '.join(sorted(missing))}")

        with tx() as cur:
            cur.execute(
                """INSERT INTO scheduled_entries
                       (description, reference, payee_id, target_scenario_id,
                        interval_unit, interval_count, next_date)
                   VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (description, reference, payee_id, target_scenario_id,
                 interval_unit, interval_count, next_date))
            sched_id = cur.fetchone()["id"]
            for n, ln in enumerate(lines, start=1):
                cur.execute(
                    """INSERT INTO scheduled_entry_lines
                           (scheduled_entry_id, line_no, account_id, amount, memo)
                       VALUES (%s, %s, (SELECT id FROM accounts WHERE code = %s), %s, %s)""",
                    (sched_id, n, ln["code"], ln["amount"], ln["memo"]))
            if tag_names:
                _sync_tags(cur, "scheduled_entry_tags", "scheduled_entry_id",
                          sched_id, tag_names)
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        if wants_json:
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        return flash_redirect("/scheduled", err=msg)
    ok_msg = f"Schedule {description!r} created — next on {next_date}"
    if wants_json:
        return JSONResponse({"ok": True, "redirect": flash_url("/scheduled", ok=ok_msg)})
    return flash_redirect("/scheduled", ok=ok_msg)


@app.post("/scheduled/{scheduled_id}/toggle-active")
def toggle_schedule(scheduled_id: int, request: Request, csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        with tx() as cur:
            cur.execute(
                "UPDATE scheduled_entries SET is_active = NOT is_active WHERE id = %s",
                (scheduled_id,))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/scheduled", err=msg)
    return flash_redirect("/scheduled", ok="Schedule updated")


@app.post("/scheduled/post")
async def post_scheduled_entries(request: Request):
    form = await request.form()
    try:
        require_csrf(request, form.get("csrf_token"))
    except ValueError as e:
        return flash_redirect("/scheduled", err=str(e))

    entry_ids = [int(v) for v in form.getlist("entry_id") if v]
    if not entry_ids:
        return flash_redirect("/scheduled", err="Select at least one entry to post")

    posted, errors = [], []
    for eid in entry_ids:
        try:
            staged = q1("""SELECT e.*, se.target_scenario_id
                             FROM journal_entries e
                             JOIN scheduled_entries se ON se.id = e.scheduled_entry_id
                            WHERE e.id = %s""", (eid,))
            if not staged:
                raise ValueError(f"#{eid}: not a pending scheduled entry")
            if staged["promoted_entry_id"] is not None:
                raise ValueError(f"#{eid}: already posted")
            with tx() as cur:
                cur.execute(
                    """INSERT INTO journal_entries
                           (scenario_id, entry_date, description, reference,
                            payee_id, created_by_user_id)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
                    (staged["target_scenario_id"], staged["entry_date"],
                     staged["description"], staged["reference"], staged["payee_id"],
                     auth.current_user(request)["user_id"]))
                new_id = cur.fetchone()["id"]
                cur.execute(
                    """INSERT INTO journal_lines
                           (entry_id, line_no, account_id, amount, memo)
                       SELECT %s, line_no, account_id, amount, memo
                         FROM journal_lines WHERE entry_id = %s""",
                    (new_id, eid))
                cur.execute(
                    """INSERT INTO journal_entry_tags (entry_id, tag_id)
                       SELECT %s, tag_id FROM journal_entry_tags WHERE entry_id = %s""",
                    (new_id, eid))
                cur.execute(
                    "UPDATE journal_entries SET promoted_entry_id = %s WHERE id = %s",
                    (new_id, eid))
            posted.append(eid)
        except (ValueError, psycopg.Error) as e:
            errors.append(_pg_msg(e) if isinstance(e, psycopg.Error) else str(e))

    ok_msg = f"Posted {len(posted)} entr{'y' if len(posted) == 1 else 'ies'}" if posted else None
    err_msg = "; ".join(errors) or None
    return flash_redirect("/scheduled", ok=ok_msg, err=err_msg)


# ---------------------------------------------------------------------------
# Entry templates — reusable scaffolding for New entry's "Load template"
# picker. Not postings themselves and not tracked once loaded: loading one
# just fills the form (entirely client-side — see entry_templates.js and
# the #templates-data blob below), the same as typing it by hand.
# ---------------------------------------------------------------------------
def templates_full():
    tpls = q("""SELECT t.id, t.name, t.description, t.reference, t.payee_id,
                       p.name AS payee_name
                  FROM entry_templates t
                  LEFT JOIN payees p ON p.id = t.payee_id
                 ORDER BY t.name""")
    ids = [t["id"] for t in tpls]
    lines_by_t, tags_by_t = {}, {}
    if ids:
        for ln in q("""SELECT l.template_id, a.code, l.debit, l.credit, l.memo
                         FROM entry_template_lines l
                         JOIN accounts a ON a.id = l.account_id
                        WHERE l.template_id = ANY(%s)
                        ORDER BY l.template_id, l.line_no""", (ids,)):
            lines_by_t.setdefault(ln["template_id"], []).append({
                "code": ln["code"],
                "debit": str(ln["debit"]) if ln["debit"] else None,
                "credit": str(ln["credit"]) if ln["credit"] else None,
                "memo": ln["memo"],
            })
        for tg in q("""SELECT ett.template_id, tg.name FROM entry_template_tags ett
                        JOIN tags tg ON tg.id = ett.tag_id
                       WHERE ett.template_id = ANY(%s) ORDER BY tg.name""", (ids,)):
            tags_by_t.setdefault(tg["template_id"], []).append(tg["name"])
    for t in tpls:
        t["lines"] = lines_by_t.get(t["id"], [])
        t["tags"] = tags_by_t.get(t["id"], [])
    return tpls


@app.get("/templates")
def templates_page(request: Request, ok: str = None, err: str = None):
    postable = postable_accounts_for_pickers()
    active_payees = q("SELECT id, name FROM payees WHERE is_active ORDER BY name")
    return templates.TemplateResponse(request, "entry_templates.html", {
        "nav": "templates", "tpls": templates_full(),
        "accounts": postable, "payees": active_payees, "all_tags": all_tags(),
        "ok": ok, "err": err,
    })


@app.post("/templates")
async def create_template(request: Request):
    form = await request.form()
    wants_json = "application/json" in request.headers.get("accept", "")
    try:
        require_csrf(request, form.get("csrf_token"))
        name = (form.get("name") or "").strip()
        if not name:
            raise ValueError("Template name is required")
        lines = _parse_lines(form)
        total = round(sum(ln["amount"] for ln in lines), 2)
        if total != 0:
            raise ValueError("Template lines must balance (debits = credits)")
        description = (form.get("description") or "").strip()
        if not description:
            raise ValueError("Description is required")
        reference = (form.get("reference") or "").strip() or None
        payee_id = int(form.get("payee_id")) if form.get("payee_id") else None
        tag_names = _parse_tags(form.get("tags", ""))

        codes = {ln["code"] for ln in lines}
        found = {r["code"] for r in q(
            "SELECT code FROM accounts WHERE code = ANY(%s)", (list(codes),))}
        missing = codes - found
        if missing:
            raise ValueError(f"Unknown account code: {', '.join(sorted(missing))}")

        with tx() as cur:
            cur.execute(
                """INSERT INTO entry_templates (name, description, reference, payee_id)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (name, description, reference, payee_id))
            tpl_id = cur.fetchone()["id"]
            for n, ln in enumerate(lines, start=1):
                cur.execute(
                    """INSERT INTO entry_template_lines
                           (template_id, line_no, account_id, amount, memo)
                       VALUES (%s, %s, (SELECT id FROM accounts WHERE code = %s), %s, %s)""",
                    (tpl_id, n, ln["code"], ln["amount"], ln["memo"]))
            if tag_names:
                _sync_tags(cur, "entry_template_tags", "template_id", tpl_id, tag_names)
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        if wants_json:
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        return flash_redirect("/templates", err=msg)
    ok_msg = f"Template {name!r} saved"
    if wants_json:
        return JSONResponse({"ok": True, "redirect": flash_url("/templates", ok=ok_msg)})
    return flash_redirect("/templates", ok=ok_msg)


@app.post("/templates/{template_id}/delete")
def delete_template(template_id: int, request: Request, csrf_token: str = Form(...)):
    try:
        require_csrf(request, csrf_token)
        with tx() as cur:
            cur.execute("DELETE FROM entry_templates WHERE id = %s", (template_id,))
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/templates", err=msg)
    return flash_redirect("/templates", ok="Template deleted")


# ---------------------------------------------------------------------------
# JSON API — same data, no HTML. Point scripts (or curiosity) here.
# ---------------------------------------------------------------------------
@app.get("/api/trial-balance")
def api_trial_balance(scenario: str = "ACTUAL", as_of: str = None):
    return q("SELECT * FROM fn_trial_balance(%s, %s)", (scenario, as_of))


@app.get("/api/accounts")
def api_accounts():
    return q("SELECT * FROM v_dim_account ORDER BY sort_path")


@app.get("/api/scenarios")
def api_scenarios():
    return scenarios_all()


@app.get("/api/entries")
def api_entries(scenario: str = None, date_from: str = None,
                date_to: str = None):
    where, params = ["TRUE"], []
    if scenario:
        where.append("scenario_code = %s")
        params.append(scenario)
    if date_from:
        where.append("entry_date >= %s")
        params.append(date_from)
    if date_to:
        where.append("entry_date <= %s")
        params.append(date_to)
    return q(f"""SELECT * FROM v_fact_lines WHERE {' AND '.join(where)}
                 ORDER BY entry_date DESC, entry_id DESC, line_id LIMIT 1000""",
             params)


@app.get("/api/monthly-activity")
def api_monthly(scenario: str = None):
    if scenario:
        return q("""SELECT * FROM v_monthly_activity WHERE scenario_code = %s
                    ORDER BY month, account_code""", (scenario,))
    return q("SELECT * FROM v_monthly_activity ORDER BY month, account_code")


# ---------------------------------------------------------------------------
def _pg_msg(e: Exception) -> str:
    """Surface the RAISE EXCEPTION message from a trigger, without the noise."""
    diag = getattr(e, "diag", None)
    if diag is not None and diag.message_primary:
        return diag.message_primary
    return str(e).splitlines()[0]

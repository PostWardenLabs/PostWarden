"""Libro — a personal general ledger with scenarios.

HTML screens for humans, /api/* JSON for machines, PostgreSQL for the truth.
"""
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import psycopg
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .db import q, q1, tx

BASE = Path(__file__).parent
app = FastAPI(title="Libro")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def money(v) -> str:
    if v is None:
        return ""
    return f"{v:,.2f}"


templates.env.filters["money"] = money

ACCOUNT_TYPES = ["asset", "liability", "equity", "income", "expense"]
TYPE_LABELS = {
    "asset": "Assets", "liability": "Liabilities", "equity": "Equity",
    "income": "Income", "expense": "Expenses",
}
SCENARIO_TYPES = ["actual", "budget", "forecast", "what_if"]


def scenarios_all():
    return q("""SELECT s.*, (SELECT COUNT(*) FROM journal_entries e
                             WHERE e.scenario_id = s.id) AS entry_count
                FROM scenarios s ORDER BY s.scenario_type, s.code""")


def flash_redirect(url: str, ok: str = None, err: str = None):
    params = {}
    if ok:
        params["ok"] = ok
    if err:
        params["err"] = err
    sep = "&" if "?" in url else "?"
    return RedirectResponse(url + (sep + urlencode(params) if params else ""),
                            status_code=303)


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
# Chart of accounts
# ---------------------------------------------------------------------------
@app.get("/accounts")
def accounts_page(request: Request, ok: str = None, err: str = None):
    accounts = q("SELECT * FROM v_dim_account ORDER BY sort_path")
    return templates.TemplateResponse(request, "accounts.html", {
        "nav": "accounts", "accounts": accounts,
        "account_types": ACCOUNT_TYPES, "type_labels": TYPE_LABELS,
        "ok": ok, "err": err,
    })


@app.post("/accounts")
def create_account(code: str = Form(...), name: str = Form(...),
                   account_type: str = Form(...), parent_id: str = Form(""),
                   is_postable: str = Form(None)):
    try:
        with tx() as cur:
            cur.execute(
                """INSERT INTO accounts (code, name, account_type, parent_id, is_postable)
                   VALUES (%s, %s, %s, %s, %s)""",
                (code.strip(), name.strip(), account_type,
                 int(parent_id) if parent_id else None,
                 is_postable is not None),
            )
    except psycopg.Error as e:
        return flash_redirect("/accounts", err=_pg_msg(e))
    return flash_redirect("/accounts", ok=f"Account {code} — {name} created")


@app.post("/accounts/{account_id}/toggle-active")
def toggle_account(account_id: int):
    try:
        with tx() as cur:
            cur.execute(
                "UPDATE accounts SET is_active = NOT is_active WHERE id = %s",
                (account_id,))
    except psycopg.Error as e:
        return flash_redirect("/accounts", err=_pg_msg(e))
    return flash_redirect("/accounts", ok="Account updated")


# ---------------------------------------------------------------------------
# Journal entry — the keyboard-first screen
# ---------------------------------------------------------------------------
@app.get("/entries/new")
def entry_new(request: Request, err: str = None):
    postable = q("""SELECT id, code, name, path FROM v_dim_account
                    WHERE is_postable AND is_active ORDER BY sort_path""")
    scen = [s for s in scenarios_all() if not s["is_locked"]]
    return templates.TemplateResponse(request, "entry_new.html", {
        "nav": "new", "accounts": postable, "scenarios": scen,
        "today": date.today().isoformat(), "err": err,
    })


def _parse_lines(form) -> list[dict]:
    """Turn parallel account[]/debit[]/credit[]/memo[] arrays into line dicts.

    Rules mirror the paper form: a line needs an account and exactly one of
    debit or credit, strictly positive. Blank rows are ignored.
    """
    accounts = form.getlist("account")
    debits = form.getlist("debit")
    credits = form.getlist("credit")
    memos = form.getlist("memo")
    lines = []
    for i, acct in enumerate(accounts):
        acct = (acct or "").strip()
        d = (debits[i] if i < len(debits) else "").strip()
        c = (credits[i] if i < len(credits) else "").strip()
        memo = (memos[i] if i < len(memos) else "").strip() or None
        if not acct and not d and not c:
            continue  # blank row
        code = acct.split("·")[0].split(" ")[0].strip()
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
    try:
        lines = _parse_lines(form)
        entry_date = form.get("entry_date") or date.today().isoformat()
        scenario_id = int(form.get("scenario_id"))
        description = (form.get("description") or "").strip()
        reference = (form.get("reference") or "").strip() or None
        if not description:
            raise ValueError("Description is required")

        with tx() as cur:
            cur.execute(
                """INSERT INTO journal_entries
                       (scenario_id, entry_date, description, reference)
                   VALUES (%s, %s, %s, %s) RETURNING id""",
                (scenario_id, entry_date, description, reference))
            entry_id = cur.fetchone()["id"]
            for n, ln in enumerate(lines, start=1):
                cur.execute(
                    """INSERT INTO journal_lines
                           (entry_id, line_no, account_id, amount, memo)
                       VALUES (%s, %s,
                               (SELECT id FROM accounts WHERE code = %s),
                               %s, %s)""",
                    (entry_id, n, ln["code"], ln["amount"], ln["memo"]))
        # the deferred trigger has now blessed the entry at COMMIT
    except (ValueError, psycopg.Error) as e:
        msg = _pg_msg(e) if isinstance(e, psycopg.Error) else str(e)
        return flash_redirect("/entries/new", err=msg)
    return flash_redirect("/entries", ok=f"Entry #{entry_id} posted")


# ---------------------------------------------------------------------------
# Journal browser
# ---------------------------------------------------------------------------
@app.get("/entries")
def entries_page(request: Request, scenario: str = "", date_from: str = "",
                 date_to: str = "", qtext: str = "", ok: str = None,
                 err: str = None):
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

    entries = q(f"""
        SELECT e.id, e.entry_date, e.description, e.reference,
               e.reverses_entry_id, s.code AS scenario_code,
               s.is_locked AS scenario_locked,
               (SELECT COALESCE(SUM(l.debit), 0) FROM journal_lines l
                 WHERE l.entry_id = e.id) AS total_debits,
               (SELECT COALESCE(SUM(l.credit), 0) FROM journal_lines l
                 WHERE l.entry_id = e.id) AS total_credits,
               (SELECT r.id FROM journal_entries r
                 WHERE r.reverses_entry_id = e.id LIMIT 1) AS reversed_by
          FROM journal_entries e
          JOIN scenarios s ON s.id = e.scenario_id
         WHERE {' AND '.join(where)}
         ORDER BY e.entry_date DESC, e.id DESC
         LIMIT 200""", params)

    ids = [e["id"] for e in entries]
    lines_by_entry = {}
    if ids:
        for ln in q("""SELECT l.entry_id, l.line_no, l.debit, l.credit,
                              l.memo, a.code AS account_code,
                              a.name AS account_name
                         FROM journal_lines l
                         JOIN accounts a ON a.id = l.account_id
                        WHERE l.entry_id = ANY(%s)
                        ORDER BY l.entry_id, l.line_no""", (ids,)):
            lines_by_entry.setdefault(ln["entry_id"], []).append(ln)

    return templates.TemplateResponse(request, "entries.html", {
        "nav": "entries", "entries": entries, "lines_by_entry": lines_by_entry,
        "scenarios": scenarios_all(), "scenario": scenario,
        "date_from": date_from, "date_to": date_to, "qtext": qtext,
        "ok": ok, "err": err,
    })


@app.post("/entries/{entry_id}/reverse")
def reverse_entry(entry_id: int):
    try:
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
                        reverses_entry_id)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (orig["scenario_id"], date.today(),
                 f"Reversal of #{entry_id} — {orig['description']}",
                 orig["reference"], entry_id))
            new_id = cur.fetchone()["id"]
            cur.execute(
                """INSERT INTO journal_lines
                       (entry_id, line_no, account_id, amount, memo)
                   SELECT %s, line_no, account_id, -amount, memo
                     FROM journal_lines WHERE entry_id = %s""",
                (new_id, entry_id))
    except psycopg.Error as e:
        return flash_redirect("/entries", err=_pg_msg(e))
    return flash_redirect("/entries",
                          ok=f"Entry #{entry_id} reversed by #{new_id}")


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
@app.get("/scenarios")
def scenarios_page(request: Request, ok: str = None, err: str = None):
    return templates.TemplateResponse(request, "scenarios.html", {
        "nav": "scenarios", "scenarios": scenarios_all(),
        "scenario_types": SCENARIO_TYPES, "ok": ok, "err": err,
    })


@app.post("/scenarios")
def create_scenario(code: str = Form(...), name: str = Form(...),
                    scenario_type: str = Form(...),
                    enforce_balance: str = Form(None),
                    notes: str = Form("")):
    try:
        with tx() as cur:
            cur.execute(
                """INSERT INTO scenarios
                       (code, name, scenario_type, enforce_balance, notes)
                   VALUES (%s, %s, %s, %s, %s)""",
                (code.strip().upper(), name.strip(), scenario_type,
                 enforce_balance is not None, notes.strip() or None))
    except psycopg.Error as e:
        return flash_redirect("/scenarios", err=_pg_msg(e))
    return flash_redirect("/scenarios", ok=f"Scenario {code.upper()} created")


@app.post("/scenarios/{scenario_id}/toggle-lock")
def toggle_lock(scenario_id: int):
    try:
        with tx() as cur:
            cur.execute(
                "UPDATE scenarios SET is_locked = NOT is_locked WHERE id = %s",
                (scenario_id,))
    except psycopg.Error as e:
        return flash_redirect("/scenarios", err=_pg_msg(e))
    return flash_redirect("/scenarios", ok="Scenario updated")


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

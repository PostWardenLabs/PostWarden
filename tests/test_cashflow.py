"""Exercises fn_cash_flow_lines (db/schema.sql) — the Cash Flow Statement's
per-transaction attribution — directly against Postgres, same spirit as
test_invariants.py: the thing under test is what the *database* computes,
not the app layer on top of it. See SPEC.md decision 20 for the design
this checks.

Each test posts into its own throwaway scenario (mk_scenario) rather than
ACTUAL, so fn_cash_flow_lines(scenario_code, None, None) — no date bound
at all — only ever sees that one test's own entries, with no risk of
bleeding into (or picking up) another test's data or the seeded chart.
"""
from decimal import Decimal

from conftest import mk_account, mk_entry, mk_line, mk_scenario


def cash_flow_lines(cur, scenario_code):
    cur.execute(
        "SELECT * FROM fn_cash_flow_lines(%s, NULL, NULL) ORDER BY entry_id, contra_account_id",
        (scenario_code,))
    return cur.fetchall()


def test_simple_one_to_one_attribution(conn):
    with conn.cursor() as cur:
        scen = mk_scenario(cur)
        checking = mk_account(cur, cashflow=True)
        rent = mk_account(cur, account_type="expense")
        eid = mk_entry(cur, scen["id"], "Rent")
        mk_line(cur, eid, rent["id"], 9500, line_no=1)
        mk_line(cur, eid, checking["id"], -9500, line_no=2)
    conn.commit()

    with conn.cursor() as cur:
        rows = cash_flow_lines(cur, scen["code"])
    assert len(rows) == 1
    assert rows[0]["contra_account_id"] == rent["id"]
    assert rows[0]["amount"] == -9500
    assert rows[0]["n_cash_legs"] == 1


def test_split_transaction_attributes_each_leg_its_own_amount(conn):
    """1 cash leg, N non-cash legs, same sign — a grocery run split
    Food/Household. Each leg attributes its own posted amount
    (sign-flipped); the assertion that matters is that the shares still
    sum back exactly to the cash leg's full amount."""
    with conn.cursor() as cur:
        scen = mk_scenario(cur)
        checking = mk_account(cur, cashflow=True)
        food = mk_account(cur, account_type="expense")
        household = mk_account(cur, account_type="expense")
        eid = mk_entry(cur, scen["id"], "Grocery split")
        mk_line(cur, eid, food["id"], Decimal("33.33"), line_no=1)
        mk_line(cur, eid, household["id"], Decimal("33.33"), line_no=2)
        mk_line(cur, eid, checking["id"], Decimal("-66.66"), line_no=3)
    conn.commit()

    with conn.cursor() as cur:
        rows = cash_flow_lines(cur, scen["code"])
    by_account = {r["contra_account_id"]: r["amount"] for r in rows}
    assert len(rows) == 2
    assert by_account[food["id"]] == Decimal("-33.33")
    assert by_account[household["id"]] == Decimal("-33.33")
    assert sum(by_account.values()) == Decimal("-66.66")
    assert all(r["n_cash_legs"] == 1 for r in rows)


def test_mixed_sign_noncash_legs_attribute_by_own_amount_not_proportionally(conn):
    """Gross-to-net payroll is the real-world instance of this shape: one
    cash leg, and non-cash legs that do NOT all share one sign — Salary
    Income (a credit/source) alongside Income Tax and Payroll Tax
    (debits/withholding, taken out before cash ever moved). An earlier
    version of fn_cash_flow_lines attributed each non-cash leg a share
    of cash_net weighted by its own magnitude — mathematically tidy, but
    on exactly this shape it bled part of the salary inflow onto the
    tax legs, making withheld tax appear as if it were separate cash
    that had arrived (caught against real seed data, not a synthetic
    case). The correct attribution needs no weighting at all: each
    non-cash leg's own posted amount, sign-flipped, already sums to
    cash_net exactly by the balanced-entry identity — Cash 16,500.00,
    Income Tax 3,000.00, Payroll Tax 1,500.00, Salary -21,000.00 here."""
    with conn.cursor() as cur:
        scen = mk_scenario(cur)
        checking = mk_account(cur, cashflow=True)
        income_tax = mk_account(cur, account_type="expense")
        payroll_tax = mk_account(cur, account_type="expense")
        salary = mk_account(cur, account_type="income")
        eid = mk_entry(cur, scen["id"], "Salary with tax withheld")
        mk_line(cur, eid, checking["id"], 16500.00, line_no=1)
        mk_line(cur, eid, income_tax["id"], 3000.00, line_no=2)
        mk_line(cur, eid, payroll_tax["id"], 1500.00, line_no=3)
        mk_line(cur, eid, salary["id"], -21000.00, line_no=4)
    conn.commit()

    with conn.cursor() as cur:
        rows = cash_flow_lines(cur, scen["code"])
    by_account = {r["contra_account_id"]: r["amount"] for r in rows}
    assert len(rows) == 3
    # Salary shows as the full gross inflow, taxes as real outflows —
    # not a blended net-of-withholding number on any of the three.
    assert by_account[salary["id"]] == 21000.00
    assert by_account[income_tax["id"]] == -3000.00
    assert by_account[payroll_tax["id"]] == -1500.00
    assert sum(by_account.values()) == 16500.00
    assert all(r["n_cash_legs"] == 1 for r in rows)


def test_n_cash_legs_attribute_fully_to_the_one_noncash_account_and_are_flagged(conn):
    """A payroll deposit split across two cash accounts, one income
    contra-account — unambiguous (100% of the cash effect has nowhere
    else to go but the one non-cash leg), but still flagged per spec
    since it has more than one cash leg."""
    with conn.cursor() as cur:
        scen = mk_scenario(cur)
        checking = mk_account(cur, cashflow=True)
        savings = mk_account(cur, cashflow=True)
        salary = mk_account(cur, account_type="income")
        eid = mk_entry(cur, scen["id"], "Payroll split deposit")
        mk_line(cur, eid, checking["id"], 15000, line_no=1)
        mk_line(cur, eid, savings["id"], 6000, line_no=2)
        mk_line(cur, eid, salary["id"], -21000, line_no=3)
    conn.commit()

    with conn.cursor() as cur:
        rows = cash_flow_lines(cur, scen["code"])
    assert len(rows) == 1
    assert rows[0]["contra_account_id"] == salary["id"]
    assert rows[0]["amount"] == 21000
    assert rows[0]["n_cash_legs"] == 2


def test_pure_two_leg_cash_transfer_excluded(conn):
    with conn.cursor() as cur:
        scen = mk_scenario(cur)
        checking = mk_account(cur, cashflow=True)
        savings = mk_account(cur, cashflow=True)
        eid = mk_entry(cur, scen["id"], "Move to savings")
        mk_line(cur, eid, savings["id"], 2000, line_no=1)
        mk_line(cur, eid, checking["id"], -2000, line_no=2)
    conn.commit()

    with conn.cursor() as cur:
        rows = cash_flow_lines(cur, scen["code"])
    assert rows == []


def test_pure_three_leg_cash_transfer_excluded_not_just_pairwise_zero(conn):
    """The spec is explicit this must NOT be implemented as "legs net to
    zero in pairs" — a 3-leg entry where every leg is still cash-tagged
    (checking splits into savings + physical cash) has no pair that
    nets to zero on its own, only the whole entry does. Exercises that
    the real predicate ("every leg is cash-tagged") catches this too."""
    with conn.cursor() as cur:
        scen = mk_scenario(cur)
        checking = mk_account(cur, cashflow=True)
        savings = mk_account(cur, cashflow=True)
        physical = mk_account(cur, cashflow=True)
        eid = mk_entry(cur, scen["id"], "ATM + savings top-up")
        mk_line(cur, eid, physical["id"], 300, line_no=1)
        mk_line(cur, eid, savings["id"], 700, line_no=2)
        mk_line(cur, eid, checking["id"], -1000, line_no=3)
    conn.commit()

    with conn.cursor() as cur:
        rows = cash_flow_lines(cur, scen["code"])
    assert rows == []


def test_transaction_with_no_cash_leg_is_invisible_to_the_statement(conn):
    """A credit-card expense (liability, never tagged is_cashflow) has no
    cash leg at all — Step 1 of the spec never even pulls this
    transaction_id in, regardless of what its own contra-account is."""
    with conn.cursor() as cur:
        scen = mk_scenario(cur)
        credit_card = mk_account(cur, account_type="liability")
        dining = mk_account(cur, account_type="expense")
        eid = mk_entry(cur, scen["id"], "Dinner on credit card")
        mk_line(cur, eid, dining["id"], 500, line_no=1)
        mk_line(cur, eid, credit_card["id"], -500, line_no=2)
    conn.commit()

    with conn.cursor() as cur:
        rows = cash_flow_lines(cur, scen["code"])
    assert rows == []


def test_three_way_tie_out_matches_balance_roll_forward(conn):
    """The exact check _cash_flow_tie_out() runs in the app: the
    statement's own total, net cash-leg activity post-exclusion, and
    the plain ending-minus-beginning balance across is_cashflow
    accounts, all agree — across a mix of a simple flow, a split, a
    multi-cash-leg flow, and an excluded pure transfer together."""
    with conn.cursor() as cur:
        scen = mk_scenario(cur)
        checking = mk_account(cur, cashflow=True)
        savings = mk_account(cur, cashflow=True)
        rent = mk_account(cur, account_type="expense")
        food = mk_account(cur, account_type="expense")
        household = mk_account(cur, account_type="expense")
        salary = mk_account(cur, account_type="income")
        opening_equity = mk_account(cur, account_type="equity")

        eid = mk_entry(cur, scen["id"], "Opening balance")
        mk_line(cur, eid, checking["id"], 1000, line_no=1)
        mk_line(cur, eid, opening_equity["id"], -1000, line_no=2)

        eid = mk_entry(cur, scen["id"], "Rent")
        mk_line(cur, eid, rent["id"], 500, line_no=1)
        mk_line(cur, eid, checking["id"], -500, line_no=2)

        eid = mk_entry(cur, scen["id"], "Grocery split")
        mk_line(cur, eid, food["id"], 30, line_no=1)
        mk_line(cur, eid, household["id"], 20, line_no=2)
        mk_line(cur, eid, checking["id"], -50, line_no=3)

        eid = mk_entry(cur, scen["id"], "Payroll split deposit")
        mk_line(cur, eid, checking["id"], 700, line_no=1)
        mk_line(cur, eid, savings["id"], 300, line_no=2)
        mk_line(cur, eid, salary["id"], -1000, line_no=3)

        eid = mk_entry(cur, scen["id"], "Move to savings")
        mk_line(cur, eid, savings["id"], 200, line_no=1)
        mk_line(cur, eid, checking["id"], -200, line_no=2)
    conn.commit()

    with conn.cursor() as cur:
        rows = cash_flow_lines(cur, scen["code"])
        statement_total = sum(r["amount"] for r in rows)

        cur.execute("""
            SELECT COALESCE(SUM(l.amount), 0) AS net
              FROM journal_lines l
              JOIN journal_entries e ON e.id = l.entry_id
              JOIN accounts a ON a.id = l.account_id
             WHERE e.scenario_id = %s AND a.is_cashflow
               AND e.id IN (SELECT DISTINCT entry_id FROM fn_cash_flow_lines(%s, NULL, NULL))
        """, (scen["id"], scen["code"]))
        cash_leg_net = cur.fetchone()["net"]

        cur.execute("""
            SELECT COALESCE(SUM(net), 0) AS net FROM fn_account_balances(%s, NULL)
             WHERE account_id IN (%s, %s)
        """, (scen["code"], checking["id"], savings["id"]))
        balance_delta = cur.fetchone()["net"]  # beginning is 0: nothing predates this scenario

    # 1000 (opening) - 500 (rent) - 50 (groceries) + 1000 (payroll) + 0 (pure transfer nets to zero)
    assert statement_total == 1450
    assert statement_total == cash_leg_net == balance_delta

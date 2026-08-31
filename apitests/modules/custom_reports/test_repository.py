"""`modules/custom_reports/repository.py` against real Postgres — every
dimension shape, every metric expression, every filter clause, each
asserted against the hand-derived numbers in `conftest.py`'s book."""
from decimal import Decimal

from postwarden.modules.custom_reports import repository
from postwarden.modules.custom_reports.enums import Dimension, Metric


def rows_as_pairs(rows):
    return [(r["label"], r["value"]) for r in rows]


def test_net_amount_by_month(book, conn):
    # Expenses only: Jan = Dining 100 + Groceries 250; Feb = Dining 60.
    rows = repository.run_report(conn, Metric.net_amount, Dimension.month,
                                 scenario="ACTUAL", account_type="expense")
    assert rows_as_pairs(rows) == [("2026-01", Decimal("350.00")), ("2026-02", Decimal("60.00"))]


def test_net_amount_by_account_orders_by_code(book, conn):
    rows = repository.run_report(conn, Metric.net_amount, Dimension.account,
                                 scenario="ACTUAL", account_type="expense")
    assert rows_as_pairs(rows) == [("5100 Dining", Decimal("160.00")),
                                   ("5200 Groceries", Decimal("250.00"))]
    assert rows[0]["key"] == book["dining"]["id"]


def test_net_amount_flips_credit_normal_accounts(book, conn):
    # Salary's raw amounts sum to -2000 (credit legs); the metric's
    # normal_side flip makes income read positive, per the doc's table.
    rows = repository.run_report(conn, Metric.net_amount, Dimension.account,
                                 scenario="ACTUAL", account_type="income")
    assert rows_as_pairs(rows) == [("4100 Salary", Decimal("2000.00"))]


def test_net_amount_by_tag_double_counts_overlapping_tags(book, conn):
    # e2 (Groceries 250) carries both tags, so rows sum to 600 while the
    # ungrouped total stays 410 — the documented overlapping-tags
    # property, not a bug.
    rows = repository.run_report(conn, Metric.net_amount, Dimension.tag,
                                 scenario="ACTUAL", account_type="expense")
    assert rows_as_pairs(rows) == [("food", Decimal("250.00")), ("fun", Decimal("350.00"))]
    total = repository.run_total(conn, Metric.net_amount, scenario="ACTUAL",
                                 account_type="expense")
    assert total == Decimal("410.00")


def test_net_amount_by_scenario(book, conn):
    # No scenario filter — comparing scenarios is the point.
    rows = repository.run_report(conn, Metric.net_amount, Dimension.scenario,
                                 account_type="expense")
    assert rows_as_pairs(rows) == [("ACTUAL", Decimal("410.00")), ("PLAN", Decimal("80.00"))]


def test_net_amount_by_account_level_rolls_up_to_depth(book, conn):
    # Depth 1 collapses Dining + Groceries onto their root, Expenses —
    # the same sort_path truncation fn_rollup_balance uses, composed
    # with this module's own filters.
    rows = repository.run_report(conn, Metric.net_amount, Dimension.account_level,
                                 level_depth=1, scenario="ACTUAL", account_type="expense")
    assert rows_as_pairs(rows) == [("5000 Expenses", Decimal("410.00"))]


def test_quarter_and_year_dimensions(book, conn):
    rows = repository.run_report(conn, Metric.net_amount, Dimension.quarter,
                                 scenario="ACTUAL", account_type="expense")
    assert rows_as_pairs(rows) == [("2026-Q1", Decimal("410.00"))]
    rows = repository.run_report(conn, Metric.net_amount, Dimension.year,
                                 scenario="ACTUAL", account_type="expense")
    assert rows_as_pairs(rows) == [("2026", Decimal("410.00"))]


def test_debit_and_credit_totals(book, conn):
    # Dining's legs are pure debits: 100 + 60.
    rows = repository.run_report(conn, Metric.debit_total, Dimension.account,
                                 scenario="ACTUAL", account_id=book["dining"]["id"])
    assert rows_as_pairs(rows) == [("5100 Dining", Decimal("160.00"))]
    rows = repository.run_report(conn, Metric.credit_total, Dimension.account,
                                 scenario="ACTUAL", account_id=book["dining"]["id"])
    assert rows_as_pairs(rows) == [("5100 Dining", Decimal("0.00"))]


def test_entry_count_counts_distinct_entries(book, conn):
    rows = repository.run_report(conn, Metric.entry_count, Dimension.month, scenario="ACTUAL")
    assert rows_as_pairs(rows) == [("2026-01", 2), ("2026-02", 2)]
    assert repository.run_total(conn, Metric.entry_count, scenario="ACTUAL") == 4


def test_date_range_filter(book, conn):
    rows = repository.run_report(conn, Metric.net_amount, Dimension.month,
                                 scenario="ACTUAL", account_type="expense",
                                 date_from="2026-02-01", date_to="2026-02-28")
    assert rows_as_pairs(rows) == [("2026-02", Decimal("60.00"))]


def test_account_filter_leaf_vs_subtree(book, conn):
    # Bare account_id is that leaf only; subtree walks descendants, so
    # filtering on the Expenses summary account finds its children.
    rows = repository.run_report(conn, Metric.net_amount, Dimension.month,
                                 scenario="ACTUAL", account_id=book["expenses"]["id"])
    assert rows == []
    rows = repository.run_report(conn, Metric.net_amount, Dimension.month,
                                 scenario="ACTUAL", account_id=book["expenses"]["id"], subtree=True)
    assert rows_as_pairs(rows) == [("2026-01", Decimal("350.00")), ("2026-02", Decimal("60.00"))]


def test_tag_filter_is_entry_grain(book, conn):
    # tag "food" scopes to e2 — both of its legs, so without an
    # account_type filter the balanced entry nets to zero.
    rows = repository.run_report(conn, Metric.net_amount, Dimension.account,
                                 scenario="ACTUAL", tag_id=book["food"], account_type="expense")
    assert rows_as_pairs(rows) == [("5200 Groceries", Decimal("250.00"))]
    total = repository.run_total(conn, Metric.net_amount, scenario="ACTUAL", tag_id=book["food"])
    assert total == Decimal("0.00")


def test_payee_filter(book, conn):
    rows = repository.run_report(conn, Metric.net_amount, Dimension.account,
                                 scenario="ACTUAL", payee_id=book["cafe"], account_type="expense")
    assert rows_as_pairs(rows) == [("5100 Dining", Decimal("160.00"))]


def test_empty_result_and_zero_total(book, conn):
    rows = repository.run_report(conn, Metric.net_amount, Dimension.month, scenario="NOPE")
    assert rows == []
    assert repository.run_total(conn, Metric.net_amount, scenario="NOPE") == Decimal("0")


def test_validation_lookups(book, conn):
    assert repository.scenario_exists(conn, "ACTUAL")
    assert not repository.scenario_exists(conn, "NOPE")
    assert repository.account_exists(conn, book["dining"]["id"])
    assert not repository.account_exists(conn, 999999)
    assert repository.tag_exists(conn, book["fun"])
    assert not repository.tag_exists(conn, 999999)
    assert repository.payee_exists(conn, book["cafe"])
    assert not repository.payee_exists(conn, 999999)
    assert repository.account_level_depth(conn, book["level"]["id"]) == 1
    assert repository.account_level_depth(conn, 999999) is None


def test_account_type_filter_matches_live_postgres_enum(book, conn):
    """`AccountTypeFilter` mirrors the Postgres enum by hand (see
    enums.py's docstring) — this is the check that keeps them in sync."""
    from sqlalchemy import text

    from postwarden.modules.custom_reports.enums import AccountTypeFilter
    labels = {r["label"] for r in conn.execute(text(
        "SELECT enumlabel AS label FROM pg_enum e JOIN pg_type t ON t.oid = e.enumtypid "
        "WHERE t.typname = 'account_type'")).mappings()}
    assert labels == {m.value for m in AccountTypeFilter}

"""Tests of `dashboard.service`. `_flow_by_id` is pure (no database), so
it's tested directly with synthetic line dicts — the same precedent
`modules/staging/test_service.py` already sets for testing a
leading-underscore helper straight, rather than only through
`dashboard_summary`'s own end-to-end assembly."""
from postwarden.modules.dashboard import service


def test_flow_by_id_resolves_single_account_each_side():
    lines = [
        {"entry_id": "AAA111", "account_name": "Checking", "debit": 500, "credit": 0},
        {"entry_id": "AAA111", "account_name": "Salary", "debit": 0, "credit": 500},
    ]
    flow = service._flow_by_id(lines, "entry_id")
    assert flow["AAA111"] == {"debit_name": "Checking", "credit_name": "Salary"}


def test_flow_by_id_collapses_more_than_one_account_per_side_to_none():
    lines = [
        {"entry_id": "BBB222", "account_name": "Rent", "debit": 100, "credit": 0},
        {"entry_id": "BBB222", "account_name": "Utilities", "debit": 50, "credit": 0},
        {"entry_id": "BBB222", "account_name": "Checking", "debit": 0, "credit": 150},
    ]
    flow = service._flow_by_id(lines, "entry_id")
    assert flow["BBB222"] == {"debit_name": None, "credit_name": "Checking"}


def test_flow_by_id_keys_independently_per_id():
    lines = [
        {"entry_id": "A", "account_name": "Checking", "debit": 100, "credit": 0},
        {"entry_id": "A", "account_name": "Salary", "debit": 0, "credit": 100},
        {"entry_id": "B", "account_name": "Rent", "debit": 50, "credit": 0},
        {"entry_id": "B", "account_name": "Checking", "debit": 0, "credit": 50},
    ]
    flow = service._flow_by_id(lines, "entry_id")
    assert set(flow) == {"A", "B"}
    assert flow["B"] == {"debit_name": "Rent", "credit_name": "Checking"}


def test_dashboard_summary_computes_net_worth_and_mtd_figures(book, conn):
    summary = service.dashboard_summary(conn)
    assert summary["today"] == book["today"].isoformat()
    assert summary["month_label"] == book["today"].strftime("%B %Y")
    assert summary["net_worth"] == 6500  # 6800 asset - 300 liability
    assert summary["mtd_income"] == 3000
    assert summary["mtd_expenses"] == 1200
    assert summary["mtd_net"] == 1800


def test_dashboard_summary_recent_entries_carry_a_flow_label(book, conn):
    summary = service.dashboard_summary(conn)
    rent = next(r for r in summary["recent"] if r["description"] == "Rent payment")
    assert rent["debit_name"] == "Rent"
    assert rent["credit_name"] == "Checking"


def test_dashboard_summary_with_no_upcoming_schedules_returns_an_empty_list(book, conn):
    summary = service.dashboard_summary(conn)
    assert summary["upcoming"] == []

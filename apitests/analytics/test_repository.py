"""Direct tests of `analytics.repository` against a real Postgres
connection (`book`/`conn`, see `./conftest.py` and `../conftest.py`)."""
from postwarden.analytics import repository


def test_trial_balance_returns_a_row_per_active_account(book, conn):
    rows = repository.trial_balance(conn, "ACTUAL", "2026-02-28")
    by_code = {r["account_code"]: r for r in rows}
    # Checking: +1000 (opening) +2000 (paycheck) -800 (rent) = 2200, all debit-normal.
    assert by_code["1100"]["net"] == 2200
    assert by_code["1100"]["debit_balance"] == 2200
    # Old Expense (5900) is inactive, and fn_trial_balance's own WHERE
    # da.is_active excludes it — unlike this module's own accounts(),
    # which has no such filter at all.
    assert "5900" not in by_code


def test_trial_balance_as_of_none_means_through_today(book, conn):
    # No as_of at all still returns rows (fn_trial_balance's own DEFAULT
    # NULL means "through today" per schema.sql) rather than erroring.
    rows = repository.trial_balance(conn, "ACTUAL", None)
    assert any(r["account_code"] == "1100" for r in rows)


def test_accounts_includes_inactive_accounts_unlike_reports_dim_accounts(book, conn):
    codes = {r["code"] for r in repository.accounts(conn)}
    assert "5900" in codes  # the inactive one from the fixture
    assert "1100" in codes


def test_accounts_ordered_by_sort_path(book, conn):
    rows = repository.accounts(conn)
    codes = [r["code"] for r in rows]
    # A parent always precedes its own children.
    assert codes.index("1000") < codes.index("1100")


def test_scenarios_includes_base_level_name_and_entry_count(book, conn):
    rows = {r["code"]: r for r in repository.scenarios(conn)}
    assert rows["ACTUAL"]["base_level_name"] == "Top level"
    assert rows["ACTUAL"]["entry_count"] == 3
    assert rows["BUDGET2"]["base_level_name"] is None
    assert rows["BUDGET2"]["entry_count"] == 0


def test_fact_lines_orders_newest_first(book, conn):
    rows = repository.fact_lines(conn, None, None, None)
    dates = [r["entry_date"].isoformat() for r in rows]
    assert dates == sorted(dates, reverse=True)


def test_fact_lines_filters_by_scenario_and_date_range(book, conn):
    rows = repository.fact_lines(conn, "ACTUAL", "2026-02-01", "2026-02-28")
    assert all(r["scenario_code"] == "ACTUAL" for r in rows)
    assert all("2026-02-01" <= r["entry_date"].isoformat() <= "2026-02-28" for r in rows)
    # January's opening-balance entry falls outside the range.
    assert not any(r["description"] == "Opening balance" for r in rows)


def test_fact_lines_unfiltered_returns_every_line(book, conn):
    rows = repository.fact_lines(conn, None, None, None)
    assert len(rows) == 6  # three entries, two lines each (BUDGET2 has none of its own)


def test_monthly_activity_groups_by_month_and_account(book, conn):
    rows = repository.monthly_activity(conn, "ACTUAL")
    checking_rows = {r["month"].isoformat(): r for r in rows if r["account_code"] == "1100"}
    # January: just the opening balance (+1000). February: paycheck (+2000) and rent (-800) net to +1200.
    assert checking_rows["2026-01-01"]["net"] == 1000
    assert checking_rows["2026-02-01"]["net"] == 1200


def test_monthly_activity_unfiltered_includes_every_scenario(book, conn):
    rows = repository.monthly_activity(conn, None)
    assert any(r["scenario_code"] == "ACTUAL" for r in rows)

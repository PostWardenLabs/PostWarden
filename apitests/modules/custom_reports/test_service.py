"""`modules/custom_reports/service.py` — the checks the type system
can't do: filter ids naming real rows, date well-formedness, the
`account_level`/`level_id` pairing, and the dimension=scenario
filter-drop rule. The query arithmetic itself is `test_repository.py`'s
job; here only `run()`'s orchestration and error paths."""
from decimal import Decimal

import pytest

from postwarden.modules.custom_reports import service
from postwarden.modules.custom_reports.enums import AccountTypeFilter, Dimension, Metric


def run(conn, **overrides):
    kwargs = dict(metric=Metric.net_amount, dimension=Dimension.month, scenario="ACTUAL",
                  date_from="", date_to="", account_id=None, subtree=False, tag_id=None,
                  payee_id=None, account_type=None, level_id=None)
    kwargs.update(overrides)
    return service.run(conn, **kwargs)


def test_run_returns_rows_total_and_count(book, conn):
    result = run(conn, account_type=AccountTypeFilter.expense)
    assert result["row_count"] == 2
    assert result["total"] == Decimal("410.00")
    assert result["rows"][0] == {"key": "2026-01", "label": "2026-01", "value": Decimal("350.00")}


def test_unknown_scenario_rejected(book, conn):
    with pytest.raises(ValueError, match="Unknown scenario 'NOPE'"):
        run(conn, scenario="NOPE")


def test_scenario_dimension_drops_the_scenario_filter(book, conn):
    # Even a bogus scenario value passes — the filter is dropped for
    # this dimension (comparing scenarios is the point), so the config
    # a user reaches by flipping the dimension dropdown keeps working.
    result = run(conn, dimension=Dimension.scenario, scenario="NOPE",
                 account_type=AccountTypeFilter.expense)
    assert [r["label"] for r in result["rows"]] == ["ACTUAL", "PLAN"]


def test_unknown_filter_ids_rejected(book, conn):
    with pytest.raises(ValueError, match="Account #999999 not found"):
        run(conn, account_id=999999)
    with pytest.raises(ValueError, match="Tag #999999 not found"):
        run(conn, tag_id=999999)
    with pytest.raises(ValueError, match="Payee #999999 not found"):
        run(conn, payee_id=999999)


def test_malformed_date_rejected(book, conn):
    with pytest.raises(ValueError, match="date_from must be a YYYY-MM-DD date"):
        run(conn, date_from="not-a-date")
    with pytest.raises(ValueError, match="date_to must be a YYYY-MM-DD date"):
        run(conn, date_to="2026-13-99")


def test_account_level_requires_and_resolves_level_id(book, conn):
    with pytest.raises(ValueError, match="needs a level_id"):
        run(conn, dimension=Dimension.account_level)
    with pytest.raises(ValueError, match="Level #999999 not found"):
        run(conn, dimension=Dimension.account_level, level_id=999999)
    result = run(conn, dimension=Dimension.account_level, level_id=book["level"]["id"],
                 account_type=AccountTypeFilter.expense)
    assert result["rows"] == [
        {"key": book["expenses"]["id"], "label": "5000 Expenses", "value": Decimal("410.00")}]


def test_level_id_is_ignored_for_other_dimensions(book, conn):
    # A leftover level_id from a previous dimension choice shouldn't
    # break the report — tolerated, same as the app's other pages
    # tolerate stale URL params.
    result = run(conn, level_id=999999, account_type=AccountTypeFilter.expense)
    assert result["row_count"] == 2

"""Direct tests of modules.imports.repository — proves the raw SQL
wiring against a real Postgres. Parsing/staging-orchestration behavior is
covered by test_service.py/test_router.py instead — this file just
proves each function returns/does what its own docstring says."""
from decimal import Decimal

from postwarden.modules.imports import repository as repo


def test_staging_scenario_id_returns_none_when_none_configured(conn):
    assert repo.staging_scenario_id(conn) is None


def test_staging_scenario_id_returns_the_staging_scenario(book, conn):
    assert repo.staging_scenario_id(conn) == book["staging"]["id"]


def test_account_ids_by_code_returns_only_what_exists(book, conn):
    found = repo.account_ids_by_code(conn, ["1100", "4100", "9999"])
    assert found == {"1100": book["checking"]["id"], "4100": book["salary"]["id"]}


def test_upsert_payee_returns_the_same_id_on_conflict(conn):
    first = repo.upsert_payee(conn, "Acme")
    second = repo.upsert_payee(conn, "Acme")
    assert first == second


def test_insert_import_batch_and_recent_batches_round_trip(book, conn):
    batch_id = repo.insert_import_batch(
        conn, filename="bank.csv", target_scenario_id=book["actual"]["id"],
        imported_by_user_id=None, row_count=2)
    [row] = repo.recent_batches(conn, 10)
    assert row["id"] == batch_id
    assert row["filename"] == "bank.csv"
    assert row["row_count"] == 2
    assert row["target_scenario_code"] == "ACTUAL"
    assert row["imported_by"] is None


def test_recent_batches_orders_newest_first_and_respects_limit(book, conn):
    for name in ("a.csv", "b.csv", "c.csv"):
        repo.insert_import_batch(conn, filename=name, target_scenario_id=book["actual"]["id"],
                                  imported_by_user_id=None, row_count=1)
    rows = repo.recent_batches(conn, 2)
    assert len(rows) == 2
    assert rows[0]["filename"] == "c.csv"


def test_insert_staged_entry_and_insert_line_round_trip(book, conn):
    batch_id = repo.insert_import_batch(
        conn, filename="bank.csv", target_scenario_id=book["actual"]["id"],
        imported_by_user_id=None, row_count=1)
    entry_id = repo.insert_staged_entry(
        conn, scenario_id=book["staging"]["id"], entry_date="2026-08-01",
        description="Imported entry", reference="REF1", payee_id=None, import_batch_id=batch_id)
    repo.insert_line(conn, entry_id=entry_id, line_no=1, account_id=book["checking"]["id"],
                      amount=Decimal("40.00"), memo=None)
    repo.insert_line(conn, entry_id=entry_id, line_no=2, account_id=book["salary"]["id"],
                      amount=Decimal("-40.00"), memo=None)
    repo.check_deferred_constraints(conn)  # must not raise: the entry balances

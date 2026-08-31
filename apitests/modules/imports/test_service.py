"""DB-backed tests of modules.imports.service — both importers' parsing,
the shared `stage_import_groups` landing step, and the base64 round-trip
the mapped importer's preview/commit split relies on."""
from decimal import Decimal

import pytest

from postwarden.modules.imports import repository as repo
from postwarden.modules.imports import service


def _csv(*rows: str) -> str:
    return "\n".join(rows) + "\n"


def test_parse_csv_import_groups_rows_by_entry_number(book, conn):
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,Imported entry,{book['checking']['code']},40,",
        f"1,2026-08-01,Imported entry,{book['salary']['code']},,40",
    )
    groups, errors = service.parse_csv_import(conn, content)
    assert errors == []
    [group] = groups
    assert group["entry_date"] == "2026-08-01"
    assert group["description"] == "Imported entry"
    amounts = {ln["code"]: ln["amount"] for ln in group["lines"]}
    assert amounts[book["checking"]["code"]] == Decimal("40.00")
    assert amounts[book["salary"]["code"]] == Decimal("-40.00")


def test_parse_csv_import_reports_bad_rows_and_keeps_the_valid_ones(book, conn):
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        # Entry 1: valid.
        f"1,2026-08-01,Good entry,{book['checking']['code']},40,",
        f"1,2026-08-01,Good entry,{book['salary']['code']},,40",
        # Entry 2: unbalanced.
        f"2,2026-08-02,Bad entry,{book['checking']['code']},50,",
        f"2,2026-08-02,Bad entry,{book['salary']['code']},,30",
        # Entry 3: unknown account code.
        "3,2026-08-03,Unknown account,NOPE999,10,",
    )
    groups, errors = service.parse_csv_import(conn, content)
    assert [g["description"] for g in groups] == ["Good entry"]
    assert any("doesn't balance" in e for e in errors)
    assert any("unknown account code" in e for e in errors)


def test_parse_csv_import_rejects_a_file_missing_required_columns(conn):
    groups, errors = service.parse_csv_import(conn, "Date,Description\n2026-08-01,Nope\n")
    assert groups == []
    assert "Missing required column(s)" in errors[0]


def test_parse_csv_import_rejects_an_empty_file(conn):
    groups, errors = service.parse_csv_import(conn, "")
    assert groups == []
    assert errors == ["The file is empty"]


def test_stage_import_groups_lands_entries_in_staging_with_a_payee(book, conn):
    groups = [{"entry_date": "2026-08-01", "description": "Imported entry", "reference": "REF1",
               "payee_name": "Acme", "lines": [
                   {"code": book["checking"]["code"], "amount": Decimal("40.00"), "memo": None},
                   {"code": book["salary"]["code"], "amount": Decimal("-40.00"), "memo": None},
               ]}]
    batch_id = service.stage_import_groups(conn, groups, "bank.csv", book["actual"]["id"], None)
    [batch] = repo.recent_batches(conn, 10)
    assert batch["id"] == batch_id
    assert batch["row_count"] == 1


def test_stage_import_groups_rejects_an_unknown_account_code(book, conn):
    groups = [{"entry_date": "2026-08-01", "description": "x", "reference": None,
               "payee_name": None, "lines": [
                   {"code": "NOPE999", "amount": Decimal("10.00"), "memo": None},
                   {"code": book["salary"]["code"], "amount": Decimal("-10.00"), "memo": None},
               ]}]
    with pytest.raises(ValueError, match="Unknown account code: NOPE999"):
        service.stage_import_groups(conn, groups, "bank.csv", book["actual"]["id"], None)


def test_import_csv_stages_entries_end_to_end(book, conn):
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,Imported entry,{book['checking']['code']},40,",
        f"1,2026-08-01,Imported entry,{book['salary']['code']},,40",
    )
    result = service.import_csv(conn, content=content, filename="bank.csv",
                                 target_scenario_id=book["actual"]["id"])
    assert result["staged_count"] == 1
    assert result["errors"] == []
    [batch] = repo.recent_batches(conn, 10)
    assert batch["id"] == result["batch_id"]


def test_import_csv_raises_when_no_groups_parsed(book, conn):
    with pytest.raises(ValueError, match="Missing required column"):
        service.import_csv(conn, content="Date,Description\n2026-08-01,Nope\n",
                            filename="bad.csv", target_scenario_id=book["actual"]["id"])


MAPPED_COLUMN_MAP = {"account": "Account", "date": "Date", "payee": "Payee",
                      "notes": "Notes", "category": "Category", "amount": "Amount"}


def test_sniff_mapped_columns_returns_headers_in_file_order_and_sample_rows():
    content = _csv(
        "Merchant,When,Amount,Bucket",
        "Landlord,2026-08-01,-500,Rent",
        "Employer,2026-08-02,1000,",
    )
    sniff = service.sniff_mapped_columns(content)
    assert sniff["columns"] == ["Merchant", "When", "Amount", "Bucket"]
    assert sniff["sample_rows"] == [
        {"Merchant": "Landlord", "When": "2026-08-01", "Amount": "-500", "Bucket": "Rent"},
        {"Merchant": "Employer", "When": "2026-08-02", "Amount": "1000", "Bucket": ""},
    ]


def test_sniff_mapped_columns_caps_the_sample_at_sample_size():
    content = _csv("X", "1", "2", "3")
    sniff = service.sniff_mapped_columns(content, sample_size=2)
    assert len(sniff["sample_rows"]) == 2


def test_sniff_mapped_columns_rejects_an_empty_file():
    with pytest.raises(ValueError, match="The file is empty"):
        service.sniff_mapped_columns("")


def test_parse_mapped_file_reads_every_row_via_an_arbitrary_column_map():
    # A file whose own column names don't match ActualBudget's at all —
    # the whole point of the mapping step: any header works once mapped.
    content = _csv(
        "Merchant,When,Amount,Bucket",
        "Landlord,2026-08-01,-500,Rent",
    )
    column_map = {"account": "Merchant", "date": "When", "amount": "Amount", "category": "Bucket"}
    rows, errors = service.parse_mapped_file(content, column_map)
    assert errors == []
    assert rows == [{"row_no": 2, "account": "Landlord", "date": "2026-08-01", "payee": "",
                      "notes": "", "category": "Rent", "amount": "-500"}]


def test_parse_mapped_file_rejects_an_incomplete_column_map():
    content = _csv("Account,Date,Amount", "Checking,2026-08-01,10")
    rows, errors = service.parse_mapped_file(content, {"account": "Account"})
    assert rows == []
    assert "Choose a column for" in errors[0]
    assert "Entry Date" in errors[0] and "Amount" in errors[0]


def test_parse_mapped_file_rejects_a_column_map_pointing_at_a_column_the_file_lacks():
    content = _csv("Account,Date,Amount", "Checking,2026-08-01,10")
    column_map = {"account": "Account", "date": "Date", "amount": "Nope"}
    rows, errors = service.parse_mapped_file(content, column_map)
    assert rows == []
    assert "Mapped column(s) not found in the file: Nope" in errors[0]


def test_preview_mapped_summarizes_accounts_and_categories():
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
        "Checking,2026-08-02,Employer,,,1000",
    )
    preview = service.preview_mapped(content, MAPPED_COLUMN_MAP)
    assert preview["row_count"] == 2
    assert preview["accounts_found"] == ["Checking"]
    assert preview["categories_found"] == ["Rent"]
    assert preview["has_no_category_rows"] is True


def test_preview_mapped_raises_on_a_file_with_no_rows():
    content = "Account,Date,Payee,Notes,Category,Amount\n"
    with pytest.raises(ValueError, match="No rows found"):
        service.preview_mapped(content, MAPPED_COLUMN_MAP)


def test_transform_mapped_rows_maps_an_expense_row_debit_positive(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "Landlord",
             "notes": "", "category": "Rent", "amount": "-500"}]
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]}, {"Rent": book["rent"]["code"]}, flip_sign=False)
    assert errors == []
    [group] = groups
    amounts = {ln["code"]: ln["amount"] for ln in group["lines"]}
    assert amounts[book["rent"]["code"]] == Decimal("500.00")     # expense increases (debit)
    assert amounts[book["checking"]["code"]] == Decimal("-500.00")  # money decreases (credit)


def test_transform_mapped_rows_maps_an_income_row_credit_positive(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-02", "payee": "Employer",
             "notes": "", "category": "", "amount": "1000"}]
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]},
        {service.IMPORT_MAPPED_NO_CATEGORY: book["salary"]["code"]}, flip_sign=False)
    assert errors == []
    [group] = groups
    amounts = {ln["code"]: ln["amount"] for ln in group["lines"]}
    assert amounts[book["checking"]["code"]] == Decimal("1000.00")
    assert amounts[book["salary"]["code"]] == Decimal("-1000.00")


def test_transform_mapped_rows_flip_sign_inverts_every_amount(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "",
             "notes": "", "category": "Rent", "amount": "500"}]
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]}, {"Rent": book["rent"]["code"]}, flip_sign=True)
    assert errors == []
    amounts = {ln["code"]: ln["amount"] for ln in groups[0]["lines"]}
    assert amounts[book["checking"]["code"]] == Decimal("-500.00")


def test_transform_mapped_rows_skips_a_zero_amount_row(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "",
             "notes": "", "category": "Rent", "amount": "0"}]
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]}, {"Rent": book["rent"]["code"]}, flip_sign=False)
    assert groups == []
    assert errors == []


def test_transform_mapped_rows_reports_an_unmapped_account(book):
    rows = [{"row_no": 2, "account": "Savings", "date": "2026-08-01", "payee": "",
             "notes": "", "category": "Rent", "amount": "-10"}]
    groups, errors = service.transform_mapped_rows(rows, {}, {"Rent": book["rent"]["code"]}, False)
    assert groups == []
    assert "no mapping chosen for account" in errors[0]


def test_import_mapped_stages_entries_end_to_end(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    result = service.import_mapped(
        conn, content=content, filename="export.csv", target_scenario_id=book["actual"]["id"],
        column_map=MAPPED_COLUMN_MAP, account_map={"Checking": book["checking"]["code"]},
        category_map={"Rent": book["rent"]["code"]}, flip_sign=False)
    assert result["staged_count"] == 1
    assert result["errors"] == []


def test_import_mapped_stages_entries_via_an_arbitrary_column_map(book, conn):
    # Same file shape as above, but with the bank's own column names
    # instead of ActualBudget's — the actual point of the mapping step.
    content = _csv(
        "Merchant,When,Amount,Bucket",
        "Landlord,2026-08-01,-500,Rent",
    )
    column_map = {"account": "Merchant", "date": "When", "amount": "Amount", "category": "Bucket"}
    result = service.import_mapped(
        conn, content=content, filename="bank.csv", target_scenario_id=book["actual"]["id"],
        column_map=column_map, account_map={"Landlord": book["checking"]["code"]},
        category_map={"Rent": book["rent"]["code"]}, flip_sign=False)
    assert result["staged_count"] == 1
    assert result["errors"] == []


def test_import_mapped_raises_row_errors_when_the_mapping_is_incomplete(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    with pytest.raises(ValueError, match="no mapping chosen for account"):
        service.import_mapped(conn, content=content, filename="export.csv",
                               target_scenario_id=book["actual"]["id"], column_map=MAPPED_COLUMN_MAP,
                               account_map={}, category_map={}, flip_sign=False)


def test_import_mapped_raises_when_the_column_map_is_incomplete(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    with pytest.raises(ValueError, match="Choose a column for"):
        service.import_mapped(conn, content=content, filename="export.csv",
                               target_scenario_id=book["actual"]["id"], column_map={"account": "Account"},
                               account_map={}, category_map={}, flip_sign=False)


def test_import_mapped_raises_the_fallback_message_when_the_file_has_no_data_rows(book, conn):
    content = "Account,Date,Payee,Notes,Category,Amount\n"  # header only, zero rows -> zero row_errors
    with pytest.raises(ValueError, match="No valid entries produced"):
        service.import_mapped(conn, content=content, filename="export.csv",
                               target_scenario_id=book["actual"]["id"], column_map=MAPPED_COLUMN_MAP,
                               account_map={}, category_map={}, flip_sign=False)


def test_decode_upload_strips_a_bom():
    assert service.decode_upload(b"\xef\xbb\xbfDate,X\n") == "Date,X\n"


def test_decode_upload_rejects_undecodable_bytes():
    with pytest.raises(ValueError, match="Could not read the file as UTF-8"):
        service.decode_upload(b"\xff\xfe\x00\x01")


def test_encode_decode_roundtrip_preserves_content():
    content = "Account,Date\nChecking,2026-08-01\n"
    b64 = service.encode_for_roundtrip(content.encode("utf-8"))
    assert service.decode_roundtrip(b64) == content


def test_recent_batches_wraps_the_repository(book, conn):
    repo.insert_import_batch(conn, filename="bank.csv", target_scenario_id=book["actual"]["id"],
                              imported_by_user_id=None, row_count=1)
    assert [b["filename"] for b in service.recent_batches(conn)] == ["bank.csv"]

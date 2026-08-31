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
                      "memo": "Notes", "category": "Category", "amount": "Amount"}


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
                      "description": "", "memo": "", "category": "Rent", "amount": "-500"}]


def test_parse_mapped_file_reads_a_description_column_distinct_from_payee():
    # §2.1 of IMPORT_WIZARD.md: Entry Description and Line Memo are their
    # own targets now, not just Payee/Notes wearing those hats implicitly.
    content = _csv(
        "Merchant,Memo line,When,Amount",
        "Landlord,Rent for August,2026-08-01,-500",
    )
    column_map = {"account": "Merchant", "description": "Memo line", "date": "When", "amount": "Amount"}
    rows, errors = service.parse_mapped_file(content, column_map)
    assert errors == []
    [row] = rows
    assert row["description"] == "Rent for August"
    assert row["payee"] == ""


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
             "description": "", "memo": "", "category": "Rent", "amount": "-500"}]
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]}, {"Rent": book["rent"]["code"]}, flip_sign=False)
    assert errors == []
    [group] = groups
    amounts = {ln["code"]: ln["amount"] for ln in group["lines"]}
    assert amounts[book["rent"]["code"]] == Decimal("500.00")     # expense increases (debit)
    assert amounts[book["checking"]["code"]] == Decimal("-500.00")  # money decreases (credit)


def test_transform_mapped_rows_maps_an_income_row_credit_positive(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-02", "payee": "Employer",
             "description": "", "memo": "", "category": "", "amount": "1000"}]
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
             "description": "", "memo": "", "category": "Rent", "amount": "500"}]
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]}, {"Rent": book["rent"]["code"]}, flip_sign=True)
    assert errors == []
    amounts = {ln["code"]: ln["amount"] for ln in groups[0]["lines"]}
    assert amounts[book["checking"]["code"]] == Decimal("-500.00")


def test_transform_mapped_rows_skips_a_zero_amount_row(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "",
             "description": "", "memo": "", "category": "Rent", "amount": "0"}]
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]}, {"Rent": book["rent"]["code"]}, flip_sign=False)
    assert groups == []
    assert errors == []


def test_transform_mapped_rows_reports_an_unmapped_account(book):
    rows = [{"row_no": 2, "account": "Savings", "date": "2026-08-01", "payee": "",
             "description": "", "memo": "", "category": "Rent", "amount": "-10"}]
    groups, errors = service.transform_mapped_rows(rows, {}, {"Rent": book["rent"]["code"]}, False)
    assert groups == []
    assert "no mapping chosen for account" in errors[0]


def test_transform_mapped_rows_description_wins_over_the_payee_fallback(book):
    # §2.1 of IMPORT_WIZARD.md: an explicitly-mapped Entry Description
    # takes priority over the payee/category/fallback chain, which only
    # ever applies when nothing is mapped there.
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "Landlord",
             "description": "August rent", "memo": "", "category": "Rent", "amount": "-500"}]
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]}, {"Rent": book["rent"]["code"]}, flip_sign=False)
    assert errors == []
    assert groups[0]["description"] == "August rent"


def test_transform_mapped_rows_falls_back_to_payee_then_category_then_a_fixed_string(book):
    base = {"row_no": 2, "account": "Checking", "date": "2026-08-01", "description": "", "memo": "", "amount": "-500"}
    account_map = {"Checking": book["checking"]["code"]}
    category_map = {"Rent": book["rent"]["code"], service.IMPORT_MAPPED_NO_CATEGORY: book["rent"]["code"]}

    groups, _ = service.transform_mapped_rows(
        [{**base, "payee": "Landlord", "category": "Rent"}], account_map, category_map, flip_sign=False)
    assert groups[0]["description"] == "Landlord"

    groups, _ = service.transform_mapped_rows(
        [{**base, "payee": "", "category": "Rent"}], account_map, category_map, flip_sign=False)
    assert groups[0]["description"] == "Rent"

    groups, _ = service.transform_mapped_rows(
        [{**base, "payee": "", "category": ""}], account_map, category_map, flip_sign=False)
    assert groups[0]["description"] == "Imported transaction"


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


def test_sniff_dialect_defaults_a_plain_comma_iso_file():
    content = _csv("Account,Date,Amount", "Checking,2026-08-01,-500")
    assert service.sniff_dialect(content) == service.IMPORT_DEFAULT_DIALECT


def test_sniff_dialect_detects_semicolons_and_a_comma_decimal_with_dot_thousands():
    # A European bank export: ';' fields, '.' groups thousands, ','
    # is the decimal point — the exact shape IMPORT_WIZARD.md's Phase 2
    # calls out as "currently just fails, with no control anywhere to
    # fix it."
    content = _csv(
        "Konto;Datum;Zahlungsempfänger;Betrag",
        "Girokonto;2026-03-01;Vermieter;-500,00",
        "Girokonto;2026-03-02;Arbeitgeber;1.234,56",
    )
    dialect = service.sniff_dialect(content)
    assert dialect["delimiter"] == ";"
    assert dialect["decimal_separator"] == ","
    assert dialect["thousands_separator"] == "."


def test_sniff_dialect_detects_dd_mm_yyyy_dates_from_an_out_of_range_day():
    content = _csv("Account,Date,Amount", "Checking,25/03/2026,-500", "Checking,13/04/2026,1000")
    assert service.sniff_dialect(content)["date_format"] == "eu"


def test_sniff_dialect_detects_mm_dd_yyyy_dates_from_an_out_of_range_month_position():
    content = _csv("Account,Date,Amount", "Checking,03/25/2026,-500", "Checking,04/13/2026,1000")
    assert service.sniff_dialect(content)["date_format"] == "us"


def test_sniff_dialect_skips_junk_lines_above_the_real_header():
    # A title line and a blank line above the header — both have a
    # different field count than the header/data rows that follow, which
    # is the whole signal `_sniff_header_row` votes on.
    content = "Exported by MyBank on 2026-08-31\n\n" + _csv(
        "Account,Date,Amount", "Checking,2026-08-01,-500", "Checking,2026-08-02,1000")
    dialect = service.sniff_dialect(content)
    assert dialect["header_row"] == 2
    rows = service.parse_rows(content, dialect)
    assert [r["Account"] for r in rows] == ["Checking", "Checking"]


def test_sniff_dialect_detects_the_delimiter_past_a_junk_line_and_a_blank_line():
    # A blank line in the sample is enough on its own to make
    # `csv.Sniffer` give up outright (`csv.Error: Could not determine
    # delimiter`) rather than fall back to a plausible guess — this is
    # the regression case: a junk line *and* a blank line both above the
    # real header, on an otherwise unambiguous semicolon file.
    content = ("Exported from MyBank on 2026-08-31\n\n"
               + _csv("Konto;Datum;Betrag", "Girokonto;2026-08-01;-500,00"))
    dialect = service.sniff_dialect(content)
    assert dialect["delimiter"] == ";"
    assert dialect["header_row"] == 2


def test_sniff_dialect_rejects_an_empty_file():
    with pytest.raises(ValueError, match="The file is empty"):
        service.sniff_dialect("")


def test_resolve_dialect_fills_in_missing_keys_from_the_default():
    resolved = service.resolve_dialect({"delimiter": ";"})
    assert resolved["delimiter"] == ";"
    assert resolved["date_format"] == service.IMPORT_DEFAULT_DIALECT["date_format"]


def test_resolve_dialect_treats_none_the_same_as_an_empty_dict():
    assert service.resolve_dialect(None) == service.IMPORT_DEFAULT_DIALECT


def test_parse_amount_normalizes_a_comma_decimal_with_a_dot_thousands_separator():
    dialect = {"decimal_separator": ",", "thousands_separator": "."}
    assert service.parse_amount("1.234,56", dialect) == Decimal("1234.56")
    assert service.parse_amount("-500,00", dialect) == Decimal("-500.00")


def test_parse_date_reads_eu_and_us_slash_formats():
    assert service.parse_date("25/03/2026", {"date_format": "eu"}).isoformat() == "2026-03-25"
    assert service.parse_date("03/25/2026", {"date_format": "us"}).isoformat() == "2026-03-25"


def test_parse_rows_honors_a_non_default_delimiter_and_header_row():
    content = "junk line\n" + "A;B\nx;y\n"
    rows = service.parse_rows(content, {"delimiter": ";", "header_row": 1})
    assert rows == [{"A": "x", "B": "y"}]


def test_sniff_mapped_columns_honors_an_overridden_dialect():
    content = "junk\n" + "A;B\nx;y\n"
    sniff = service.sniff_mapped_columns(content, {"delimiter": ";", "header_row": 1})
    assert sniff["columns"] == ["A", "B"]
    assert sniff["sample_rows"] == [{"A": "x", "B": "y"}]


def test_parse_mapped_file_honors_an_overridden_dialect_and_reports_real_file_row_numbers():
    content = "Exported 2026-08-31\n" + _csv("Konto;Datum;Betrag", "Girokonto;2026-08-01;-500")
    dialect = {"delimiter": ";", "header_row": 1}
    column_map = {"account": "Konto", "date": "Datum", "amount": "Betrag"}
    rows, errors = service.parse_mapped_file(content, column_map, dialect)
    assert errors == []
    # Header is real file line 2 (one junk line skipped), so the first
    # data row is real file line 3 — not line 2, what a `header_row: 0`
    # assumption would have said.
    assert rows[0]["row_no"] == 3
    assert rows[0]["account"] == "Girokonto"


def test_transform_mapped_rows_applies_a_european_decimal_dialect(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "Landlord",
             "description": "", "memo": "", "category": "Rent", "amount": "1.234,56"}]
    dialect = {**service.IMPORT_DEFAULT_DIALECT, "decimal_separator": ",", "thousands_separator": "."}
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]}, {"Rent": book["rent"]["code"]},
        flip_sign=False, dialect=dialect)
    assert errors == []
    amounts = {ln["code"]: ln["amount"] for ln in groups[0]["lines"]}
    assert amounts[book["checking"]["code"]] == Decimal("1234.56")


def test_transform_mapped_rows_applies_a_non_iso_date_dialect(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "25/03/2026", "payee": "Landlord",
             "description": "", "memo": "", "category": "Rent", "amount": "-500"}]
    dialect = {**service.IMPORT_DEFAULT_DIALECT, "date_format": "eu"}
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]}, {"Rent": book["rent"]["code"]},
        flip_sign=False, dialect=dialect)
    assert errors == []
    assert groups[0]["entry_date"] == "2026-03-25"


def test_transform_mapped_rows_reports_the_dialects_own_expected_date_format(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "not-a-date", "payee": "",
             "description": "", "memo": "", "category": "Rent", "amount": "-500"}]
    dialect = {**service.IMPORT_DEFAULT_DIALECT, "date_format": "eu"}
    groups, errors = service.transform_mapped_rows(
        rows, {"Checking": book["checking"]["code"]}, {"Rent": book["rent"]["code"]},
        flip_sign=False, dialect=dialect)
    assert groups == []
    assert "expected DD/MM/YYYY" in errors[0]


def test_import_mapped_stages_a_semicolon_european_decimal_file_end_to_end(book, conn):
    content = _csv(
        "Konto;Datum;Zahlungsempfänger;Betrag",
        "Checking;2026-08-01;Landlord;-500,00",
    )
    column_map = {"account": "Konto", "date": "Datum", "payee": "Zahlungsempfänger", "amount": "Betrag"}
    dialect = {"delimiter": ";", "decimal_separator": ",", "thousands_separator": "."}
    result = service.import_mapped(
        conn, content=content, filename="export.csv", target_scenario_id=book["actual"]["id"],
        column_map=column_map, account_map={"Checking": book["checking"]["code"]},
        category_map={service.IMPORT_MAPPED_NO_CATEGORY: book["rent"]["code"]},
        flip_sign=False, dialect=dialect)
    assert result["staged_count"] == 1
    assert result["errors"] == []


def test_recent_batches_wraps_the_repository(book, conn):
    repo.insert_import_batch(conn, filename="bank.csv", target_scenario_id=book["actual"]["id"],
                              imported_by_user_id=None, row_count=1)
    assert [b["filename"] for b in service.recent_batches(conn)] == ["bank.csv"]

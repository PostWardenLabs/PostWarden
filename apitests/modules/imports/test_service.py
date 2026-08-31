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


def test_sniff_shape_defaults_to_one_row_signed_amount_for_a_plain_export():
    sniff = service.sniff_mapped_columns(_csv(
        "Merchant,When,Amount,Bucket",
        "Landlord,2026-08-01,-500,Rent",
    ))
    shape = service.sniff_shape(sniff["columns"], sniff["sample_rows"])
    assert shape == {"rows_per_entry": "one", "group_key_column": None, "amount_style": "signed"}


def test_sniff_shape_detects_a_debit_credit_column_pair():
    sniff = service.sniff_mapped_columns(_csv(
        "Date,Description,Account code,Debit,Credit",
        "2026-08-01,Rent,100,40,",
    ))
    shape = service.sniff_shape(sniff["columns"], sniff["sample_rows"])
    assert shape["amount_style"] == "debit_credit"


def test_sniff_shape_detects_a_repeated_entry_number_column_as_the_group_key():
    sniff = service.sniff_mapped_columns(_csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        "1,2026-08-01,Rent,100,40,",
        "1,2026-08-01,Rent,200,,40",
    ))
    shape = service.sniff_shape(sniff["columns"], sniff["sample_rows"])
    assert shape == {"rows_per_entry": "grouped", "group_key_column": "Entry #", "amount_style": "debit_credit"}


def test_sniff_shape_ignores_an_id_shaped_column_that_never_actually_repeats():
    # "Transaction ID" looks group-key-shaped by name, but every value in
    # the sample is unique — not actually evidence of grouping.
    sniff = service.sniff_mapped_columns(_csv(
        "Transaction ID,Date,Amount",
        "TX1,2026-08-01,-40",
        "TX2,2026-08-02,100",
    ))
    shape = service.sniff_shape(sniff["columns"], sniff["sample_rows"])
    assert shape["rows_per_entry"] == "one"
    assert shape["group_key_column"] is None


def test_sniff_shape_ignores_a_repeated_column_with_no_id_shaped_name():
    # "Category" repeats plenty in a real file, but nothing about its name
    # suggests it groups rows into one entry.
    sniff = service.sniff_mapped_columns(_csv(
        "Date,Amount,Category",
        "2026-08-01,-40,Rent",
        "2026-08-02,-30,Rent",
    ))
    shape = service.sniff_shape(sniff["columns"], sniff["sample_rows"])
    assert shape["rows_per_entry"] == "one"
    assert shape["group_key_column"] is None


def test_target_fields_for_shape_covers_the_one_row_signed_case():
    fields = service.target_fields_for_shape({"rows_per_entry": "one", "amount_style": "signed"})
    by_key = {f["key"]: f for f in fields}
    assert by_key["account"]["required"] and by_key["account"]["lookup_capable"]
    assert by_key["category"]["lookup_capable"] and not by_key["category"]["required"]
    assert "amount" in by_key and "debit" not in by_key and "credit" not in by_key
    assert "group_key" not in by_key


def test_target_fields_for_shape_covers_the_grouped_debit_credit_case():
    fields = service.target_fields_for_shape({"rows_per_entry": "grouped", "amount_style": "debit_credit"})
    by_key = {f["key"]: f for f in fields}
    assert by_key["group_key"]["required"] and not by_key["group_key"]["lookup_capable"]
    assert by_key["account"]["required"] and by_key["account"]["lookup_capable"]
    assert by_key["description"]["required"]
    assert "debit" in by_key and "credit" in by_key and "amount" not in by_key
    assert "category" not in by_key


GROUPED_DEBIT_CREDIT_SHAPE = {"rows_per_entry": "grouped", "group_key_column": "Entry #",
                               "amount_style": "debit_credit"}
GROUPED_SIGNED_SHAPE = {"rows_per_entry": "grouped", "group_key_column": "Entry #", "amount_style": "signed"}
ONE_ROW_DEBIT_CREDIT_SHAPE = {"rows_per_entry": "one", "group_key_column": None, "amount_style": "debit_credit"}
GROUPED_COLUMN_MAP = {"group_key": "Entry #", "date": "Date", "description": "Description",
                       "account": "Account code", "debit": "Debit", "credit": "Credit"}
DIRECT_CODE_KIND = {"account": service.IMPORT_COLUMN_KIND_CODE}


def test_parse_file_and_transform_rows_match_parse_csv_import_for_a_grouped_debit_credit_direct_code_file(book, conn):
    # The literal equivalence check IMPORT_WIZARD.md §7 Phase 4 calls
    # for: today's Export-CSV shape (grouped, Debit/Credit, real account
    # codes, no value_maps at all) must stage identically whether it goes
    # through the old `parse_csv_import` or the new `parse_file` +
    # `transform_rows`.
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,Imported entry,{book['checking']['code']},40,",
        f"1,2026-08-01,Imported entry,{book['salary']['code']},,40",
    )
    old_groups, old_errors = service.parse_csv_import(conn, content)
    assert old_errors == []

    rows, parse_errors = service.parse_file(content, GROUPED_DEBIT_CREDIT_SHAPE, GROUPED_COLUMN_MAP)
    assert parse_errors == []
    new_groups, new_errors = service.transform_rows(
        rows, GROUPED_DEBIT_CREDIT_SHAPE, column_kinds=DIRECT_CODE_KIND, value_maps={}, flip_sign=False)
    assert new_errors == []
    assert new_groups == old_groups


def test_transform_rows_grouped_debit_credit_reports_one_balance_error_per_group_not_per_row(book):
    # `parse_csv_import`'s own historical granularity: a group that
    # doesn't balance is dropped with exactly one error, keyed to the
    # group's first row — not one error per row inside it.
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,Off by ten,{book['checking']['code']},50,",
        f"1,2026-08-01,Off by ten,{book['salary']['code']},,30",
    )
    rows, _ = service.parse_file(content, GROUPED_DEBIT_CREDIT_SHAPE, GROUPED_COLUMN_MAP)
    groups, errors = service.transform_rows(
        rows, GROUPED_DEBIT_CREDIT_SHAPE, column_kinds=DIRECT_CODE_KIND, value_maps={}, flip_sign=False)
    assert groups == []
    assert len(errors) == 1
    assert errors[0]["row_no"] == 2
    assert "doesn't balance" in errors[0]["message"]


def test_transform_rows_grouped_signed_accepts_a_repeated_key_with_one_signed_amount_per_row(book):
    # A new combination with no old-importer equivalent: several rows
    # sharing a group key, each with its own signed Amount rather than a
    # Debit/Credit pair.
    content = _csv(
        "Entry #,Date,Description,Account code,Amount",
        f"1,2026-08-01,Rent,{book['checking']['code']},-500",
        f"1,2026-08-01,Rent,{book['rent']['code']},500",
    )
    column_map = {"group_key": "Entry #", "date": "Date", "description": "Description",
                   "account": "Account code", "amount": "Amount"}
    rows, parse_errors = service.parse_file(content, GROUPED_SIGNED_SHAPE, column_map)
    assert parse_errors == []
    groups, errors = service.transform_rows(
        rows, GROUPED_SIGNED_SHAPE, column_kinds=DIRECT_CODE_KIND, value_maps={}, flip_sign=False)
    assert errors == []
    [group] = groups
    amounts = {ln["code"]: ln["amount"] for ln in group["lines"]}
    assert amounts[book["checking"]["code"]] == Decimal("-500.00")
    assert amounts[book["rent"]["code"]] == Decimal("500.00")


def test_transform_rows_one_row_debit_credit_expresses_a_single_entrys_net_as_two_columns(book):
    # Another new combination: one row = one entry (like the mapped
    # importer always worked), but the net is a Debit/Credit pair instead
    # of one signed Amount column.
    content = _csv(
        "Account,Date,Debit,Credit,Category",
        "Checking,2026-08-01,,500,Rent",
    )
    column_map = {"account": "Account", "date": "Date", "debit": "Debit", "credit": "Credit",
                  "category": "Category"}
    rows, parse_errors = service.parse_file(content, ONE_ROW_DEBIT_CREDIT_SHAPE, column_map)
    assert parse_errors == []
    groups, errors = service.transform_rows(
        rows, ONE_ROW_DEBIT_CREDIT_SHAPE,
        column_kinds={"account": "label", "category": "label"},
        value_maps={"account": {"Checking": book["checking"]["code"]},
                    "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False)
    assert errors == []
    [group] = groups
    amounts = {ln["code"]: ln["amount"] for ln in group["lines"]}
    assert amounts[book["checking"]["code"]] == Decimal("-500.00")
    assert amounts[book["rent"]["code"]] == Decimal("500.00")


def test_transform_rows_one_row_signed_matches_transform_mapped_rows_for_an_expense(book):
    # Confirms the generalized "one" path reproduces `transform_mapped_
    # rows`' own shipped behavior (expense row, debit-positive) once
    # `column_kinds` defaults to "label" and `value_maps` carries the same
    # two maps `account_map`/`category_map` used to be.
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    column_map = {"account": "Account", "date": "Date", "payee": "Payee", "memo": "Notes",
                  "category": "Category", "amount": "Amount"}
    rows, _ = service.parse_file(content, service.IMPORT_DEFAULT_SHAPE, column_map)
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={}, value_maps={
            "account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False)
    assert errors == []
    amounts = {ln["code"]: ln["amount"] for ln in groups[0]["lines"]}
    assert amounts[book["rent"]["code"]] == Decimal("500.00")
    assert amounts[book["checking"]["code"]] == Decimal("-500.00")


def test_transform_rows_known_codes_none_trusts_a_code_kind_column_verbatim(book):
    rows = [{"row_no": 2, "group_key": "1", "date": "2026-08-01", "description": "x",
             "account": "NOPE999", "debit": "10", "credit": "", "reference": "", "payee": "", "memo": ""},
            {"row_no": 3, "group_key": "1", "date": "2026-08-01", "description": "x",
             "account": book["checking"]["code"], "debit": "", "credit": "10", "reference": "", "payee": "",
             "memo": ""}]
    groups, errors = service.transform_rows(
        rows, GROUPED_DEBIT_CREDIT_SHAPE, column_kinds=DIRECT_CODE_KIND, value_maps={}, flip_sign=False,
        known_codes=None)
    assert errors == []  # trusted verbatim — `stage_import_groups` is the one that would catch NOPE999
    [group] = groups
    assert {ln["code"] for ln in group["lines"]} == {"NOPE999", book["checking"]["code"]}


def test_transform_rows_known_codes_supplied_reports_an_unknown_code_per_row(book):
    rows = [{"row_no": 2, "group_key": "1", "date": "2026-08-01", "description": "x",
             "account": "NOPE999", "debit": "10", "credit": "", "reference": "", "payee": "", "memo": ""},
            {"row_no": 3, "group_key": "1", "date": "2026-08-01", "description": "x",
             "account": book["checking"]["code"], "debit": "", "credit": "10", "reference": "", "payee": "",
             "memo": ""}]
    groups, errors = service.transform_rows(
        rows, GROUPED_DEBIT_CREDIT_SHAPE, column_kinds=DIRECT_CODE_KIND, value_maps={}, flip_sign=False,
        known_codes={book["checking"]["code"]})
    assert groups == []
    assert errors[0]["row_no"] == 2
    assert "Unknown account code 'NOPE999'" in errors[0]["message"]


def test_known_account_codes_returns_none_when_no_column_is_code_kind(conn):
    assert service.known_account_codes(conn, "content", GROUPED_SIGNED_SHAPE, {}, {}) is None


def test_known_account_codes_resolves_real_codes_in_one_bulk_lookup(book, conn):
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,x,{book['checking']['code']},40,",
        f"1,2026-08-01,x,{book['salary']['code']},,40",
    )
    codes = service.known_account_codes(conn, content, GROUPED_DEBIT_CREDIT_SHAPE, GROUPED_COLUMN_MAP,
                                         DIRECT_CODE_KIND)
    assert codes == {book["checking"]["code"], book["salary"]["code"]}


def test_known_account_codes_returns_none_on_a_structural_parse_error(conn):
    assert service.known_account_codes(conn, "", GROUPED_DEBIT_CREDIT_SHAPE, GROUPED_COLUMN_MAP,
                                        DIRECT_CODE_KIND) is None


def test_preview_file_reports_distinct_values_for_label_kind_lookup_columns():
    content = _csv(
        "Account,Date,Amount,Category",
        "Checking,2026-08-01,-500,Rent",
        "Checking,2026-08-02,1000,",
    )
    column_map = {"account": "Account", "date": "Date", "amount": "Amount", "category": "Category"}
    preview = service.preview_file(content, service.IMPORT_DEFAULT_SHAPE, column_map, column_kinds={})
    assert preview["row_count"] == 2
    assert preview["values_found"]["account"] == {"distinct": ["Checking"], "has_blank_rows": False}
    assert preview["values_found"]["category"] == {"distinct": ["Rent"], "has_blank_rows": True}


def test_preview_file_omits_a_code_kind_column_entirely(book):
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,x,{book['checking']['code']},40,",
        f"1,2026-08-01,x,{book['salary']['code']},,40",
    )
    preview = service.preview_file(content, GROUPED_DEBIT_CREDIT_SHAPE, GROUPED_COLUMN_MAP, DIRECT_CODE_KIND)
    assert preview["values_found"] == {}  # nothing to map — same zero-friction round trip as always


def test_preview_file_raises_on_a_file_with_no_rows():
    content = "Account,Date,Amount,Category\n"
    column_map = {"account": "Account", "date": "Date", "amount": "Amount", "category": "Category"}
    with pytest.raises(ValueError, match="No rows found"):
        service.preview_file(content, service.IMPORT_DEFAULT_SHAPE, column_map, column_kinds={})


def test_validate_file_reports_row_errors_without_touching_the_database(book):
    content = _csv(
        "Account,Date,Amount,Category",
        "Checking,2026-08-01,-500,Mystery",
    )
    column_map = {"account": "Account", "date": "Date", "amount": "Amount", "category": "Category"}
    result = service.validate_file(
        content, service.IMPORT_DEFAULT_SHAPE, column_map, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}}, flip_sign=False)
    assert result["groups_count"] == 0
    assert "No mapping chosen for category 'Mystery'" in result["errors"][0]["message"]


def test_validate_file_returns_zero_errors_for_a_clean_grouped_file(book):
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,x,{book['checking']['code']},40,",
        f"1,2026-08-01,x,{book['salary']['code']},,40",
    )
    result = service.validate_file(content, GROUPED_DEBIT_CREDIT_SHAPE, GROUPED_COLUMN_MAP,
                                    column_kinds=DIRECT_CODE_KIND, value_maps={}, flip_sign=False)
    assert result == {"groups_count": 1, "errors": []}


def test_import_file_stages_a_grouped_debit_credit_file_end_to_end(book, conn):
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,Imported entry,{book['checking']['code']},40,",
        f"1,2026-08-01,Imported entry,{book['salary']['code']},,40",
    )
    result = service.import_file(
        conn, content=content, filename="bank.csv", target_scenario_id=book["actual"]["id"],
        shape=GROUPED_DEBIT_CREDIT_SHAPE, column_map=GROUPED_COLUMN_MAP, column_kinds=DIRECT_CODE_KIND,
        value_maps={}, flip_sign=False)
    assert result["staged_count"] == 1
    assert result["errors"] == []
    [batch] = repo.recent_batches(conn, 10)
    assert batch["id"] == result["batch_id"]


def test_import_file_blocks_a_grouped_file_without_confirmation_when_a_row_fails(book, conn):
    # Confirms the Phase 4 decision made before implementation started:
    # `skip_bad_rows` blocks by default for the grouped shape too, not
    # just the one-row shape — a deliberate behavior change from
    # `import_csv`'s old always-partial-stage default.
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,Good,{book['checking']['code']},40,",
        f"1,2026-08-01,Good,{book['salary']['code']},,40",
        "2,2026-08-02,Unknown account,NOPE999,10,",
    )
    known = {book["checking"]["code"], book["salary"]["code"]}
    with pytest.raises(ValueError, match="Unknown account code 'NOPE999'"):
        service.import_file(
            conn, content=content, filename="bank.csv", target_scenario_id=book["actual"]["id"],
            shape=GROUPED_DEBIT_CREDIT_SHAPE, column_map=GROUPED_COLUMN_MAP, column_kinds=DIRECT_CODE_KIND,
            value_maps={}, flip_sign=False, known_codes=known)
    assert repo.recent_batches(conn, 10) == []


def test_import_file_stages_the_good_rows_when_skip_bad_rows_is_true(book, conn):
    content = _csv(
        "Entry #,Date,Description,Account code,Debit,Credit",
        f"1,2026-08-01,Good,{book['checking']['code']},40,",
        f"1,2026-08-01,Good,{book['salary']['code']},,40",
        "2,2026-08-02,Unknown account,NOPE999,10,",
    )
    known = {book["checking"]["code"], book["salary"]["code"]}
    result = service.import_file(
        conn, content=content, filename="bank.csv", target_scenario_id=book["actual"]["id"],
        shape=GROUPED_DEBIT_CREDIT_SHAPE, column_map=GROUPED_COLUMN_MAP, column_kinds=DIRECT_CODE_KIND,
        value_maps={}, flip_sign=False, skip_bad_rows=True, known_codes=known)
    assert result["staged_count"] == 1
    assert len(result["errors"]) == 1


def test_parse_file_reads_every_row_via_an_arbitrary_column_map():
    # A file whose own column names don't match ActualBudget's at all —
    # the whole point of the mapping step: any header works once mapped.
    content = _csv(
        "Merchant,When,Amount,Bucket",
        "Landlord,2026-08-01,-500,Rent",
    )
    column_map = {"account": "Merchant", "date": "When", "amount": "Amount", "category": "Bucket"}
    rows, errors = service.parse_file(content, service.IMPORT_DEFAULT_SHAPE, column_map)
    assert errors == []
    assert rows == [{"row_no": 2, "account": "Landlord", "date": "2026-08-01", "payee": "",
                      "description": "", "memo": "", "category": "Rent", "amount": "-500"}]


def test_parse_file_reads_a_description_column_distinct_from_payee():
    # §2.1 of IMPORT_WIZARD.md: Entry Description and Line Memo are their
    # own targets now, not just Payee/Notes wearing those hats implicitly.
    content = _csv(
        "Merchant,Memo line,When,Amount",
        "Landlord,Rent for August,2026-08-01,-500",
    )
    column_map = {"account": "Merchant", "description": "Memo line", "date": "When", "amount": "Amount"}
    rows, errors = service.parse_file(content, service.IMPORT_DEFAULT_SHAPE, column_map)
    assert errors == []
    [row] = rows
    assert row["description"] == "Rent for August"
    assert row["payee"] == ""


def test_parse_file_rejects_an_incomplete_column_map():
    content = _csv("Account,Date,Amount", "Checking,2026-08-01,10")
    rows, errors = service.parse_file(content, service.IMPORT_DEFAULT_SHAPE, {"account": "Account"})
    assert rows == []
    assert "Choose a column for" in errors[0]
    assert "Entry Date" in errors[0] and "Amount" in errors[0]


def test_parse_file_rejects_a_column_map_pointing_at_a_column_the_file_lacks():
    content = _csv("Account,Date,Amount", "Checking,2026-08-01,10")
    column_map = {"account": "Account", "date": "Date", "amount": "Nope"}
    rows, errors = service.parse_file(content, service.IMPORT_DEFAULT_SHAPE, column_map)
    assert rows == []
    assert "Mapped column(s) not found in the file: Nope" in errors[0]


def test_preview_file_summarizes_accounts_and_categories():
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
        "Checking,2026-08-02,Employer,,,1000",
    )
    preview = service.preview_file(content, service.IMPORT_DEFAULT_SHAPE, MAPPED_COLUMN_MAP, column_kinds={})
    assert preview["row_count"] == 2
    assert preview["values_found"]["account"]["distinct"] == ["Checking"]
    assert preview["values_found"]["category"] == {"distinct": ["Rent"], "has_blank_rows": True}


def test_transform_rows_one_row_signed_maps_an_expense_row_debit_positive(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "Landlord",
             "description": "", "memo": "", "category": "Rent", "amount": "-500"}]
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False)
    assert errors == []
    [group] = groups
    amounts = {ln["code"]: ln["amount"] for ln in group["lines"]}
    assert amounts[book["rent"]["code"]] == Decimal("500.00")     # expense increases (debit)
    assert amounts[book["checking"]["code"]] == Decimal("-500.00")  # money decreases (credit)


def test_transform_rows_one_row_signed_maps_an_income_row_credit_positive(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-02", "payee": "Employer",
             "description": "", "memo": "", "category": "", "amount": "1000"}]
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]},
                    "category": {service.IMPORT_NO_VALUE_KEY: book["salary"]["code"]}},
        flip_sign=False)
    assert errors == []
    [group] = groups
    amounts = {ln["code"]: ln["amount"] for ln in group["lines"]}
    assert amounts[book["checking"]["code"]] == Decimal("1000.00")
    assert amounts[book["salary"]["code"]] == Decimal("-1000.00")


def test_transform_rows_one_row_signed_flip_sign_inverts_every_amount(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "",
             "description": "", "memo": "", "category": "Rent", "amount": "500"}]
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=True)
    assert errors == []
    amounts = {ln["code"]: ln["amount"] for ln in groups[0]["lines"]}
    assert amounts[book["checking"]["code"]] == Decimal("-500.00")


def test_transform_rows_one_row_signed_skips_a_zero_amount_row(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "",
             "description": "", "memo": "", "category": "Rent", "amount": "0"}]
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False)
    assert groups == []
    assert errors == []


def test_transform_rows_one_row_signed_reports_an_unmapped_account(book):
    rows = [{"row_no": 2, "account": "Savings", "date": "2026-08-01", "payee": "",
             "description": "", "memo": "", "category": "Rent", "amount": "-10"}]
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={},
        value_maps={"account": {}, "category": {"Rent": book["rent"]["code"]}}, flip_sign=False)
    assert groups == []
    # IMPORT_WIZARD.md §7 Phase 3 item 1 — structured, not a pre-joined
    # "Row N: ..." string, so a validation-report table can render `raw`
    # and `message` as separate columns.
    assert errors[0]["row_no"] == 2
    assert errors[0]["raw"] == rows[0]
    assert "No mapping chosen for account" in errors[0]["message"]


def test_transform_rows_one_row_signed_reports_a_non_numeric_amount(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "",
             "description": "", "memo": "", "category": "Rent", "amount": "not-a-number"}]
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False)
    assert groups == []
    assert errors[0]["row_no"] == 2
    assert "isn't numeric" in errors[0]["message"]


def test_transform_rows_one_row_signed_description_wins_over_the_payee_fallback(book):
    # §2.1 of IMPORT_WIZARD.md: an explicitly-mapped Entry Description
    # takes priority over the payee/category/fallback chain, which only
    # ever applies when nothing is mapped there.
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "Landlord",
             "description": "August rent", "memo": "", "category": "Rent", "amount": "-500"}]
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False)
    assert errors == []
    assert groups[0]["description"] == "August rent"


def test_transform_rows_one_row_signed_falls_back_to_payee_then_category_then_a_fixed_string(book):
    base = {"row_no": 2, "account": "Checking", "date": "2026-08-01", "description": "", "memo": "", "amount": "-500"}
    value_maps = {"account": {"Checking": book["checking"]["code"]},
                  "category": {"Rent": book["rent"]["code"], service.IMPORT_NO_VALUE_KEY: book["rent"]["code"]}}

    groups, _ = service.transform_rows(
        [{**base, "payee": "Landlord", "category": "Rent"}], service.IMPORT_DEFAULT_SHAPE,
        column_kinds={}, value_maps=value_maps, flip_sign=False)
    assert groups[0]["description"] == "Landlord"

    groups, _ = service.transform_rows(
        [{**base, "payee": "", "category": "Rent"}], service.IMPORT_DEFAULT_SHAPE,
        column_kinds={}, value_maps=value_maps, flip_sign=False)
    assert groups[0]["description"] == "Rent"

    groups, _ = service.transform_rows(
        [{**base, "payee": "", "category": ""}], service.IMPORT_DEFAULT_SHAPE,
        column_kinds={}, value_maps=value_maps, flip_sign=False)
    assert groups[0]["description"] == "Imported transaction"


def test_import_file_stages_one_row_signed_entries_end_to_end(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    result = service.import_file(
        conn, content=content, filename="export.csv", target_scenario_id=book["actual"]["id"],
        shape=service.IMPORT_DEFAULT_SHAPE, column_map=MAPPED_COLUMN_MAP, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False)
    assert result["staged_count"] == 1
    assert result["errors"] == []


def test_import_file_stages_entries_via_an_arbitrary_column_map(book, conn):
    # Same file shape as above, but with the bank's own column names
    # instead of ActualBudget's — the actual point of the mapping step.
    content = _csv(
        "Merchant,When,Amount,Bucket",
        "Landlord,2026-08-01,-500,Rent",
    )
    column_map = {"account": "Merchant", "date": "When", "amount": "Amount", "category": "Bucket"}
    result = service.import_file(
        conn, content=content, filename="bank.csv", target_scenario_id=book["actual"]["id"],
        shape=service.IMPORT_DEFAULT_SHAPE, column_map=column_map, column_kinds={},
        value_maps={"account": {"Landlord": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False)
    assert result["staged_count"] == 1
    assert result["errors"] == []


def test_import_file_blocks_one_row_signed_without_confirmation_when_a_row_fails_validation(book, conn):
    # IMPORT_WIZARD.md §7 Phase 3 item 2 — a row error blocks the whole
    # commit by default now (`skip_bad_rows` defaults to False), rather
    # than the old implicit "stage what worked, report the rest."
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    with pytest.raises(ValueError, match="No mapping chosen for account"):
        service.import_file(conn, content=content, filename="export.csv",
                             target_scenario_id=book["actual"]["id"], shape=service.IMPORT_DEFAULT_SHAPE,
                             column_map=MAPPED_COLUMN_MAP, column_kinds={},
                             value_maps={"account": {}, "category": {}}, flip_sign=False)
    assert repo.recent_batches(conn, 10) == []  # nothing staged


def test_import_file_stages_the_good_one_row_signed_rows_when_skip_bad_rows_is_true(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
        "Checking,2026-08-02,Employer,,,1000",
    )
    # Only "Rent" is mapped — the second row's blank category has no
    # mapping, so it should fail and the first row should still stage.
    value_maps = {"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}}
    result = service.import_file(
        conn, content=content, filename="export.csv", target_scenario_id=book["actual"]["id"],
        shape=service.IMPORT_DEFAULT_SHAPE, column_map=MAPPED_COLUMN_MAP, column_kinds={},
        value_maps=value_maps, flip_sign=False, skip_bad_rows=True)
    assert result["staged_count"] == 1
    assert len(result["errors"]) == 1
    assert result["errors"][0]["row_no"] == 3
    assert "No mapping chosen for category" in result["errors"][0]["message"]


def test_validate_file_one_row_signed_reports_row_errors_without_touching_the_database(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    result = service.validate_file(
        content, service.IMPORT_DEFAULT_SHAPE, MAPPED_COLUMN_MAP, column_kinds={},
        value_maps={"account": {}, "category": {}}, flip_sign=False)
    assert result["groups_count"] == 0
    assert len(result["errors"]) == 1
    assert "No mapping chosen for account" in result["errors"][0]["message"]
    assert repo.recent_batches(conn, 10) == []


def test_validate_file_one_row_signed_returns_zero_errors_for_a_clean_file(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    result = service.validate_file(
        content, service.IMPORT_DEFAULT_SHAPE, MAPPED_COLUMN_MAP, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False)
    assert result["groups_count"] == 1
    assert result["errors"] == []


def test_import_file_raises_when_the_column_map_is_incomplete(book, conn):
    content = _csv(
        "Account,Date,Payee,Notes,Category,Amount",
        "Checking,2026-08-01,Landlord,,Rent,-500",
    )
    with pytest.raises(ValueError, match="Choose a column for"):
        service.import_file(conn, content=content, filename="export.csv",
                             target_scenario_id=book["actual"]["id"], shape=service.IMPORT_DEFAULT_SHAPE,
                             column_map={"account": "Account"}, column_kinds={},
                             value_maps={"account": {}, "category": {}}, flip_sign=False)


def test_import_file_raises_the_fallback_message_when_the_file_has_no_data_rows(book, conn):
    content = "Account,Date,Payee,Notes,Category,Amount\n"  # header only, zero rows -> zero row_errors
    with pytest.raises(ValueError, match="No valid entries produced"):
        service.import_file(conn, content=content, filename="export.csv",
                             target_scenario_id=book["actual"]["id"], shape=service.IMPORT_DEFAULT_SHAPE,
                             column_map=MAPPED_COLUMN_MAP, column_kinds={},
                             value_maps={"account": {}, "category": {}}, flip_sign=False)


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


def test_parse_file_honors_an_overridden_dialect_and_reports_real_file_row_numbers():
    content = "Exported 2026-08-31\n" + _csv("Konto;Datum;Betrag", "Girokonto;2026-08-01;-500")
    dialect = {"delimiter": ";", "header_row": 1}
    column_map = {"account": "Konto", "date": "Datum", "amount": "Betrag"}
    rows, errors = service.parse_file(content, service.IMPORT_DEFAULT_SHAPE, column_map, dialect)
    assert errors == []
    # Header is real file line 2 (one junk line skipped), so the first
    # data row is real file line 3 — not line 2, what a `header_row: 0`
    # assumption would have said.
    assert rows[0]["row_no"] == 3
    assert rows[0]["account"] == "Girokonto"


def test_transform_rows_one_row_signed_applies_a_european_decimal_dialect(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "2026-08-01", "payee": "Landlord",
             "description": "", "memo": "", "category": "Rent", "amount": "1.234,56"}]
    dialect = {**service.IMPORT_DEFAULT_DIALECT, "decimal_separator": ",", "thousands_separator": "."}
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False, dialect=dialect)
    assert errors == []
    amounts = {ln["code"]: ln["amount"] for ln in groups[0]["lines"]}
    assert amounts[book["checking"]["code"]] == Decimal("1234.56")


def test_transform_rows_one_row_signed_applies_a_non_iso_date_dialect(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "25/03/2026", "payee": "Landlord",
             "description": "", "memo": "", "category": "Rent", "amount": "-500"}]
    dialect = {**service.IMPORT_DEFAULT_DIALECT, "date_format": "eu"}
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False, dialect=dialect)
    assert errors == []
    assert groups[0]["entry_date"] == "2026-03-25"


def test_transform_rows_one_row_signed_reports_the_dialects_own_expected_date_format(book):
    rows = [{"row_no": 2, "account": "Checking", "date": "not-a-date", "payee": "",
             "description": "", "memo": "", "category": "Rent", "amount": "-500"}]
    dialect = {**service.IMPORT_DEFAULT_DIALECT, "date_format": "eu"}
    groups, errors = service.transform_rows(
        rows, service.IMPORT_DEFAULT_SHAPE, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]}, "category": {"Rent": book["rent"]["code"]}},
        flip_sign=False, dialect=dialect)
    assert groups == []
    assert "expected DD/MM/YYYY" in errors[0]["message"]


def test_import_file_stages_a_semicolon_european_decimal_file_end_to_end(book, conn):
    content = _csv(
        "Konto;Datum;Zahlungsempfänger;Betrag",
        "Checking;2026-08-01;Landlord;-500,00",
    )
    column_map = {"account": "Konto", "date": "Datum", "payee": "Zahlungsempfänger", "amount": "Betrag"}
    dialect = {"delimiter": ";", "decimal_separator": ",", "thousands_separator": "."}
    result = service.import_file(
        conn, content=content, filename="export.csv", target_scenario_id=book["actual"]["id"],
        shape=service.IMPORT_DEFAULT_SHAPE, column_map=column_map, column_kinds={},
        value_maps={"account": {"Checking": book["checking"]["code"]},
                    "category": {service.IMPORT_NO_VALUE_KEY: book["rent"]["code"]}},
        flip_sign=False, dialect=dialect)
    assert result["staged_count"] == 1
    assert result["errors"] == []


def test_recent_batches_wraps_the_repository(book, conn):
    repo.insert_import_batch(conn, filename="bank.csv", target_scenario_id=book["actual"]["id"],
                              imported_by_user_id=None, row_count=1)
    assert [b["filename"] for b in service.recent_batches(conn)] == ["bank.csv"]

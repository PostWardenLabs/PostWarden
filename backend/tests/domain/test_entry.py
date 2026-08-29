"""Unit tests for postwarden.domain.entry — no database, no app."""
from decimal import Decimal

import pytest

from postwarden.domain.entry import parse_lines, parse_tags


def test_parse_lines_valid_debit_and_credit():
    lines = parse_lines(
        accounts=["1110", "4000"],
        debits=["100.00", ""],
        credits=["", "100.00"],
        memos=["paycheck", ""],
    )
    assert lines == [
        {"code": "1110", "amount": Decimal("100.00"), "memo": "paycheck"},
        {"code": "4000", "amount": Decimal("-100.00"), "memo": None},
    ]


def test_parse_lines_skips_fully_blank_rows():
    lines = parse_lines(
        accounts=["1110", ""],
        debits=["50", ""],
        credits=["", ""],
        memos=["", ""],
    )
    assert len(lines) == 1
    assert lines[0]["code"] == "1110"


def test_parse_lines_missing_account_raises():
    with pytest.raises(ValueError, match="missing account"):
        parse_lines(accounts=[""], debits=["50"], credits=[""], memos=[""])


def test_parse_lines_non_numeric_amount_raises():
    with pytest.raises(ValueError, match="must be numbers"):
        parse_lines(accounts=["1110"], debits=["abc"], credits=[""], memos=[""])


def test_parse_lines_negative_amount_raises():
    with pytest.raises(ValueError, match="must be positive"):
        parse_lines(accounts=["1110"], debits=["-5"], credits=[""], memos=[""])


def test_parse_lines_both_debit_and_credit_raises():
    with pytest.raises(ValueError, match="exactly one of debit or credit"):
        parse_lines(accounts=["1110"], debits=["50"], credits=["50"], memos=[""])


def test_parse_lines_neither_debit_nor_credit_raises():
    with pytest.raises(ValueError, match="exactly one of debit or credit"):
        parse_lines(accounts=["1110"], debits=["0"], credits=["0"], memos=[""])


def test_parse_lines_no_lines_at_all_raises():
    with pytest.raises(ValueError, match="no lines"):
        parse_lines(accounts=[], debits=[], credits=[], memos=[])


def test_parse_lines_amount_is_decimal_not_float():
    # 0.1 + 0.2 != 0.3 in float; must not leak into stored amounts.
    lines = parse_lines(accounts=["1110"], debits=["0.1"], credits=[""], memos=[""])
    assert lines[0]["amount"] == Decimal("0.10")


def test_parse_tags_dedupes_and_lowercases():
    assert parse_tags("Work, work, Travel") == ["work", "travel"]


def test_parse_tags_ignores_blank_pieces():
    assert parse_tags(" , travel, ") == ["travel"]


def test_parse_tags_empty_string_is_empty_list():
    assert parse_tags("") == []


def test_parse_tags_rejects_invalid_characters():
    with pytest.raises(ValueError, match="Invalid tag"):
        parse_tags("no$good")


def test_parse_tags_rejects_over_40_chars():
    with pytest.raises(ValueError, match="Invalid tag"):
        parse_tags("a" * 41)

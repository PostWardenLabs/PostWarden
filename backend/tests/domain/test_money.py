"""Unit tests for postwarden.domain.money — no database, no app.

New tests, not a port: the legacy `_pct_variance`/`_variance_amount`/
`_pct_of`/`_divide` were file-private helpers with no direct test
coverage of their own (only indirectly, through route-level HTML
assertions). These exercise the behavior each docstring documents.
"""
from decimal import Decimal

from postwarden.domain.money import divide, normalize_zero, pct_of, pct_variance, variance_amount


def test_normalize_zero_drops_negative_sign():
    assert str(normalize_zero(Decimal("-0.00"))) == "0.00"
    assert normalize_zero(Decimal("0")) == 0


def test_normalize_zero_leaves_nonzero_alone():
    assert normalize_zero(Decimal("-5")) == Decimal("-5")
    assert normalize_zero(Decimal("5")) == Decimal("5")


def test_pct_variance_default_is_new_over_old_against_compare_val():
    # base=112, compare_val=100 -> actual came in 12% ahead of budget.
    assert pct_variance(Decimal("112"), Decimal("100")) == Decimal("12.0")


def test_pct_variance_pct_of_base_swaps_which_side_is_new():
    # compare_val=112, base=100 -> budget came in 12% ahead of actual.
    assert pct_variance(Decimal("100"), Decimal("112"), pct_of_base=True) == Decimal("12.0")


def test_pct_variance_none_when_denominator_is_zero():
    assert pct_variance(Decimal("100"), Decimal("0")) is None
    assert pct_variance(Decimal("0"), Decimal("100"), pct_of_base=True) is None


def test_variance_amount_default_is_base_minus_compare():
    assert variance_amount(Decimal("112"), Decimal("100")) == Decimal("12")


def test_variance_amount_pct_of_base_flips_the_sign_with_the_percentage():
    assert variance_amount(Decimal("100"), Decimal("112"), pct_of_base=True) == Decimal("12")


def test_pct_of_none_when_total_is_zero():
    assert pct_of(Decimal("50"), Decimal("0")) is None


def test_pct_of_computes_share():
    assert pct_of(Decimal("25"), Decimal("200")) == Decimal("12.5")


def test_divide_propagates_none():
    assert divide(None, 3) is None


def test_divide_divides():
    assert divide(Decimal("9"), 3) == Decimal("3")

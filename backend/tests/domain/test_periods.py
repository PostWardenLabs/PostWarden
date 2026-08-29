"""Unit tests for postwarden.domain.periods — no database, no app."""
from postwarden.domain.periods import (
    month_options,
    shift_date_by_month,
    shift_month,
    shift_range,
    split_periods,
)


def test_shift_date_by_month_clamps_day_to_target_month_length():
    # Jan 31 minus a month is Dec 31, not an invalid Feb 31.
    assert shift_date_by_month("2026-01-31", -1) == "2025-12-31"


def test_shift_date_by_month_clamps_into_february():
    assert shift_date_by_month("2026-03-31", -1) == "2026-02-28"


def test_shift_date_by_month_forward_across_year_boundary():
    assert shift_date_by_month("2026-12-15", 2) == "2027-02-15"


def test_shift_range_preserves_inclusive_span():
    # A 3-day range (Aug 1-3) slides to the 3 days immediately before/after.
    prev_from, prev_to, next_from, next_to = shift_range("2026-08-01", "2026-08-03")
    assert (prev_from, prev_to) == ("2026-07-29", "2026-07-31")
    assert (next_from, next_to) == ("2026-08-04", "2026-08-06")


def test_shift_range_handles_a_custom_90_day_window_without_snapping():
    prev_from, prev_to, next_from, next_to = shift_range("2026-01-01", "2026-03-31")
    span_days = 90
    assert prev_to == "2025-12-31"
    assert next_from == "2026-04-01"
    # prev window is exactly as long as the original.
    from datetime import date
    assert (date.fromisoformat(prev_to) - date.fromisoformat(prev_from)).days + 1 == span_days


def test_shift_month_always_snaps_to_day_1():
    assert shift_month("2026-08-15", 1) == "2026-09-01"
    assert shift_month("2026-01-01", -1) == "2025-12-01"


def test_month_options_spans_symmetrically_around_this_month():
    opts = month_options(span=2)
    assert len(opts) == 5
    # Middle option is the current month; every option is YYYY-MM.
    assert all(len(o) == 7 for o in opts)
    assert len(set(opts)) == 5


def test_split_periods_empty_range_returns_empty():
    assert split_periods("", "", "monthly") == []
    assert split_periods("2026-03-01", "2026-01-01", "monthly") == []


def test_split_periods_unrecognized_split_returns_empty():
    assert split_periods("2026-01-01", "2026-03-01", "weekly") == []


def test_split_periods_monthly_clips_to_the_requested_range():
    periods = split_periods("2026-08-15", "2026-10-03", "monthly")
    assert [p["label"] for p in periods] == ["2026-08", "2026-09", "2026-10"]
    assert periods[0]["date_from"] == "2026-08-15"  # clipped, not Aug 1
    assert periods[0]["partial"] is True
    assert periods[1]["date_from"] == "2026-09-01"
    assert periods[1]["partial"] is False
    assert periods[2]["date_to"] == "2026-10-03"  # clipped, not Oct 31
    assert periods[2]["partial"] is True


def test_split_periods_quarterly_labels():
    periods = split_periods("2026-01-01", "2026-12-31", "quarterly")
    assert [p["label"] for p in periods] == ["2026-Q1", "2026-Q2", "2026-Q3", "2026-Q4"]
    assert all(p["partial"] is False for p in periods)


def test_split_periods_yearly_labels():
    periods = split_periods("2025-06-01", "2026-06-01", "yearly")
    assert [p["label"] for p in periods] == ["2025", "2026"]

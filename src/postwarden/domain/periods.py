"""Pure date-period arithmetic — prev/next navigation and calendar-aligned
splitting, shared across every report that has a date range or an "as of"
date.

No framework or IO imports — `month_options()` reads the system clock
via `date.today()`, which is fine for the domain layer's "no
framework/IO" rule: no database, no HTTP, no request object.
"""
import calendar
from datetime import date, timedelta


def shift_date_by_month(date_iso: str, delta_months: int) -> str:
    """Shifts a full date by whole calendar months, clamping the day to
    the target month's real length (Jan 31 minus a month is Dec 31, not
    an invalid Feb 31) — same clamping `dateutil.relativedelta` would do,
    without the dependency. Shared "as of" prev/next navigation
    (UI_CONSISTENCY_AUDIT.md §5.6) for every point-in-time report —
    Trial Balance, Balance Sheet, Variance — same shape `shift_month()`
    already uses for Budget Grid's own month field, generalized to a
    real date instead of always snapping to day 1."""
    d = date.fromisoformat(date_iso)
    total = d.month - 1 + delta_months
    year, month = d.year + total // 12, total % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


def shift_range(date_from_iso: str, date_to_iso: str) -> tuple[str, str, str, str]:
    """Slides a date range by its own inclusive length — (prev_from,
    prev_to, next_from, next_to). Shared prev/next-period navigation
    (UI_CONSISTENCY_AUDIT.md §5.6) for every range report — Income
    Statement, Cash Flow. The window's own length defines what "one
    period" means rather than a hardcoded month/quarter assumption, so
    clicking through works the same way whether the range on screen is
    exactly a calendar month, a quarter, or something a user typed by
    hand — a 90-day custom range slides by 90 days, not snapped to any
    calendar boundary it didn't already have."""
    d_from, d_to = date.fromisoformat(date_from_iso), date.fromisoformat(date_to_iso)
    span = (d_to - d_from).days + 1
    prev_to = d_from - timedelta(days=1)
    prev_from = prev_to - timedelta(days=span - 1)
    next_from = d_to + timedelta(days=1)
    next_to = next_from + timedelta(days=span - 1)
    return prev_from.isoformat(), prev_to.isoformat(), next_from.isoformat(), next_to.isoformat()


def shift_month(month: str, delta_months: int) -> str:
    """Shifts a `YYYY-MM-01` (or any date within the month) by whole
    calendar months, always snapping back to day 1 — the Budget grid's
    own month field is never a specific day, unlike shift_date_by_month's
    real dates."""
    d = date.fromisoformat(month)
    total = d.month - 1 + delta_months
    return date(d.year + total // 12, total % 12 + 1, 1).isoformat()


def month_options(span: int = 36) -> list[str]:
    """Options for the Month combo box (BACKLOG.md: typing a month let an
    invalid one like "2026-13" reach date.fromisoformat() and 500 —
    <input type="month"> only *usually* rejects that server-side, and
    apparently doesn't in every browser). A real <select> can't submit a
    value that isn't one of its own options, which closes that off
    entirely, not just narrows it. -span..+span months around *today*,
    not the currently selected month — so the option list itself doesn't
    shift around as paging through prev/next moves the selection near
    either edge of it; span=36 (six years) comfortably covers a personal
    budget's realistic planning/lookback horizon either direction."""
    today_month = date.today().replace(day=1).isoformat()
    return [shift_month(today_month, d)[:7] for d in range(-span, span + 1)]


def advance_date(d: date, unit: str, count: int) -> date:
    """Steps a real date forward by `count` day/week/month units — ported
    from `app/main.py`'s module-level `_advance_date`, `modules/
    scheduling`'s own recurrence-rule stepper (`service.
    materialize_due_schedules` calls this right after posting a
    schedule's occurrence, to compute its next `next_date`). Month-
    stepping clamps the day the same way `shift_month`/
    `shift_date_by_month` already do above (Jan 31 plus a month is Feb
    28 or 29, never an invalid Feb 31) — this is the third function in
    this module with that exact clamp, ported separately only because
    `_advance_date` also has to pick which of day/week/month applies,
    which neither of the other two needs. Unlike every other function in
    this module, this one takes and returns a real `date`, not an ISO
    string — its one caller already has `scheduled_entries.next_date` as
    a `date` (a DB column value, not a query-string param), so there is
    no string round-trip to do."""
    if unit == "day":
        return d + timedelta(days=count)
    if unit == "week":
        return d + timedelta(weeks=count)
    if unit == "month":
        total = d.month - 1 + count
        year, month = d.year + total // 12, total % 12 + 1
        day = min(d.day, calendar.monthrange(year, month)[1])
        return date(year, month, day)
    raise ValueError(f"Unknown interval unit: {unit}")


def split_periods(date_from: str, date_to: str, split: str) -> list[dict]:
    """Breaks [date_from, date_to] into calendar-aligned sub-periods for
    Income Statement's Split view (see the route's own `split` param) —
    real calendar months/quarters/years, not even day-slicing. Each
    period is clipped to the requested range at both ends rather than
    expanded outward to a whole calendar period, so a custom range like
    Aug 15-Oct 3 split quarterly never totals days outside what
    date_from/date_to actually asked for; `partial` flags a clipped edge
    so the caller can show the real covered span next to the calendar-
    period label instead of silently implying a full quarter. An
    unrecognized/empty `split` (or an inverted range) returns [] — the
    caller's own signal to fall back to the single-range report, same as
    `compare=""` already means "no comparison" elsewhere. Capped at 60
    periods (5 years monthly) as a plain sanity limit — nothing about the
    feature needs it, it's just guarding against an accidental date range
    turning into thousands of one-day SQL round trips. Also returns []
    for an empty date_from/date_to — meaning "unbounded" to the income
    statement rows function; there's no calendar period to align an
    open-ended range to, so Split silently falls back to the single-range
    report rather than raising on an empty string."""
    if not date_from or not date_to:
        return []
    start, end = date.fromisoformat(date_from), date.fromisoformat(date_to)
    if start > end:
        return []
    if split == "monthly":
        step, label, first = 1, (lambda d: d.strftime("%Y-%m")), (lambda d: date(d.year, d.month, 1))
    elif split == "quarterly":
        step = 3
        label = lambda d: f"{d.year}-Q{(d.month - 1) // 3 + 1}"
        first = lambda d: date(d.year, (d.month - 1) // 3 * 3 + 1, 1)
    elif split == "yearly":
        step, label, first = 12, (lambda d: str(d.year)), (lambda d: date(d.year, 1, 1))
    else:
        return []

    out = []
    cur = first(start)
    while cur <= end and len(out) < 60:
        total = cur.month - 1 + step
        nxt = date(cur.year + total // 12, total % 12 + 1, 1)
        period_end = nxt - timedelta(days=1)
        period_from, period_to = max(cur, start), min(period_end, end)
        out.append({
            "label": label(cur), "date_from": period_from.isoformat(), "date_to": period_to.isoformat(),
            "partial": period_from != cur or period_to != period_end,
        })
        cur = nxt
    return out

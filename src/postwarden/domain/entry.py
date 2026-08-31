"""Pure journal-entry line parsing and tag-name validation.

Ported from `app/main.py`'s module-level `_parse_lines`/`_parse_tags`,
docstrings kept close to verbatim. `parse_lines` is the one function that
needed a real signature change, not just a rename, to satisfy the
domain layer's "zero framework/IO imports" rule: the legacy version took
a Starlette `FormData` object and called `.getlist(...)` on it directly.
Here it takes four plain parallel lists instead — the router extracts
`form.getlist("account")` etc. and passes the lists in, so this module
never imports FastAPI/Starlette at all. Amounts are `Decimal`, not the
legacy `float` — see money.py's module docstring for why.

The balance invariant itself (debits == credits across an entry's lines)
is deliberately *not* re-checked here — it lives in a `DEFERRABLE
INITIALLY DEFERRED` constraint trigger in `db/schema.sql`
(`SPEC.md` decision 2), the one place the rule is enforced, so there is
nothing to duplicate at the app layer."""
import re
from decimal import Decimal, InvalidOperation

# Matches tags.name's own CHECK constraint in db/schema.sql.
TAG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9 _-]{0,39}$")


def parse_lines(accounts: list[str], debits: list[str], credits: list[str],
                 memos: list[str]) -> list[dict]:
    """Turn parallel account/debit/credit/memo lists into line dicts.

    Rules mirror the paper form: a line needs an account and exactly one
    of debit or credit, strictly positive. Blank rows are ignored. The
    account field is a combobox in the UI, so its value is already a
    bare code; no "code · name" text to split here the way a free-text
    field would need — this is just defense in depth against a client
    that isn't the browser UI.
    """
    lines = []
    for i, acct in enumerate(accounts):
        code = (acct or "").strip()
        d = (debits[i] if i < len(debits) else "").strip()
        c = (credits[i] if i < len(credits) else "").strip()
        memo = (memos[i] if i < len(memos) else "").strip() or None
        if not code and not d and not c:
            continue  # blank row
        if not code:
            raise ValueError(f"Line {i + 1}: missing account")
        try:
            dv = Decimal(d) if d else Decimal("0")
            cv = Decimal(c) if c else Decimal("0")
        except InvalidOperation:
            raise ValueError(f"Line {i + 1}: debit and credit must be numbers")
        if dv < 0 or cv < 0:
            raise ValueError(f"Line {i + 1}: amounts must be positive")
        if (dv > 0) == (cv > 0):
            raise ValueError(
                f"Line {i + 1}: enter exactly one of debit or credit")
        lines.append({"code": code, "amount": (dv - cv).quantize(Decimal("0.01")), "memo": memo})
    if not lines:
        raise ValueError("The entry has no lines")
    return lines


def parse_tags(raw: str) -> list[str]:
    """Comma-separated tag names from the tag-input widget -> a clean,
    deduped, validated list — matches tags.name's CHECK constraint so a
    bad tag fails here with a plain message instead of a raw
    constraint-violation error. Shared by journal entries and scheduled
    entries, which both attach tags the same way."""
    seen = []
    for piece in (raw or "").split(","):
        name = piece.strip().lower()
        if not name or name in seen:
            continue
        if not TAG_PATTERN.match(name):
            raise ValueError(
                f"Invalid tag {name!r}: letters, numbers, spaces, - and _ only, max 40 chars")
        seen.append(name)
    return seen

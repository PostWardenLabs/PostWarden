"""Validation and orchestration for the reference module — Accounts,
Account levels, Scenarios, Payees, Tags. Every function here takes a
SQLAlchemy `Connection` and reads/writes through `repository.py`, never
raw SQL of its own — same convention every prior module established.
Ported from `app/main.py`'s `create_account`, `quick_create_account`,
`toggle_account`/`toggle_account_cashflow`, `create_account_level`,
`rename_account_level`/`delete_account_level`, `create_scenario`,
`toggle_lock`, `create_payee`/`quick_create_payee`, `toggle_payee`,
`rename_payee`, `delete_payee`, `merge_payees`, `create_tag`,
`toggle_tag`, `rename_tag`, `delete_tag`, `merge_tags`.

Five functions raise `ValueError(f"... not found")` on an unknown id
where their legacy originals silently no-op'd — see `repository.py`'s
own docstring for which five and why (`toggle_account_active`,
`toggle_account_cashflow`, `toggle_scenario_lock`, `rename_account_
level`, `delete_account_level`)."""
from ...domain.entry import parse_tags
from . import repository as repo

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def list_accounts(conn, level_id: int | None = None) -> list[dict]:
    return repo.list_accounts(conn, level_id)


def create_account(conn, *, code: str, name: str, account_type: str,
                    parent_id: int | None, is_postable: bool, is_cashflow: bool) -> dict:
    """No manual required-field check beyond stripping, same as legacy —
    `accounts.code`/`accounts.name`'s own `CHECK` constraints reject a
    blank or malformed value at the `INSERT`, surfaced by `errors.
    pg_message` same as any other trigger/constraint violation."""
    return repo.insert_account(
        conn, code=code.strip(), name=name.strip(), account_type=account_type,
        parent_id=parent_id, is_postable=is_postable, is_cashflow=is_cashflow)


def quick_create_account(conn, *, name: str, parent_id: int | None,
                          account_type: str | None, is_postable: bool) -> dict:
    """Ported from `quick_create_account`. `parent_id` (when given) wins:
    the new leaf inherits its parent's own `account_type` rather than
    trusting a possibly-disagreeing caller-supplied one. The generated
    code (`repository.next_account_code`) is what powers accounts.html's
    "+" picker — the bottom-of-page form (`create_account` above) is
    still there for anyone who wants an exact code."""
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required")
    if parent_id:
        acct_type = repo.account_type_of(conn, parent_id)
        if acct_type is None:
            raise ValueError("Unknown parent account")
    else:
        if not account_type:
            raise ValueError("Choose an account type")
        acct_type = account_type
    code = repo.next_account_code(conn, acct_type)
    return repo.insert_account(
        conn, code=code, name=name, account_type=acct_type, parent_id=parent_id,
        is_postable=is_postable, is_cashflow=False)


def toggle_account_active(conn, account_id: int) -> dict:
    row = repo.toggle_account_active(conn, account_id)
    if row is None:
        raise ValueError(f"Account #{account_id} not found")
    return row


def toggle_account_cashflow(conn, account_id: int) -> dict:
    row = repo.toggle_account_cashflow(conn, account_id)
    if row is None:
        raise ValueError(f"Account #{account_id} not found")
    return row


# ---------------------------------------------------------------------------
# Account levels
# ---------------------------------------------------------------------------

def list_account_levels(conn) -> list[dict]:
    return repo.account_levels_all(conn)


def create_account_level(conn, name: str, depth: int) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required")
    if depth <= 0:
        raise ValueError("Depth must be a positive number")
    return repo.insert_account_level(conn, name, depth)


def rename_account_level(conn, level_id: int, name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required")
    if repo.rename_account_level(conn, level_id, name) == 0:
        raise ValueError(f"Level #{level_id} not found")
    return name


def delete_account_level(conn, level_id: int) -> None:
    if repo.delete_account_level(conn, level_id) == 0:
        raise ValueError(f"Level #{level_id} not found")


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

def list_scenarios(conn) -> list[dict]:
    return repo.scenarios_all(conn)


def create_scenario(conn, *, code: str, name: str, scenario_type: str, enforce_balance: bool,
                     income_statement_only: bool, base_level_id: int | None,
                     notes: str | None) -> dict:
    """No manual required-field check beyond stripping/upper-casing, same
    as legacy — `scenarios.code`'s own `CHECK` (uppercase, `^[A-Z0-9_]
    {2,24}$`) and the three `actual_*`/`staging_*` constraints reject
    anything invalid at the `INSERT`."""
    return repo.insert_scenario(
        conn, code=code.strip().upper(), name=name.strip(), scenario_type=scenario_type,
        enforce_balance=enforce_balance, income_statement_only=income_statement_only,
        base_level_id=base_level_id, notes=(notes or "").strip() or None)


def toggle_scenario_lock(conn, scenario_id: int) -> dict:
    row = repo.toggle_scenario_lock(conn, scenario_id)
    if row is None:
        raise ValueError(f"Scenario #{scenario_id} not found")
    return row


# ---------------------------------------------------------------------------
# Payees
# ---------------------------------------------------------------------------

def list_payees(conn) -> list[dict]:
    return repo.payees_all(conn)


def create_payee(conn, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Payee name is required")
    return repo.insert_payee(conn, name)


def quick_create_payee(conn, name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Payee name is required")
    return repo.quick_create_payee(conn, name)


def toggle_payee_active(conn, payee_id: int) -> dict:
    row = repo.toggle_payee_active(conn, payee_id)
    if row is None:
        raise ValueError(f"Payee #{payee_id} not found")
    return row


def rename_payee(conn, payee_id: int, name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise ValueError("Payee name is required")
    if repo.rename_payee(conn, payee_id, name) == 0:
        raise ValueError(f"Payee #{payee_id} not found")
    return name


def delete_payee(conn, payee_id: int) -> str:
    name = repo.delete_payee(conn, payee_id)
    if name is None:
        raise ValueError(f"Payee #{payee_id} not found")
    return name


def merge_payees(conn, payee_ids: list[int], target_name: str) -> tuple[int, int]:
    """Returns `(merged_count, entries_affected)`, same two figures
    legacy's own flash message reports. Ported from `merge_payees`."""
    if len(payee_ids) < 2:
        raise ValueError("Select at least two payees to merge")
    target_name = (target_name or "").strip()
    if not target_name:
        raise ValueError("A name is required")
    survivor_id, other_ids = payee_ids[0], payee_ids[1:]
    affected = repo.merge_payees(conn, survivor_id, other_ids, target_name)
    if affected is None:
        raise ValueError(f"Payee #{survivor_id} not found")
    return len(payee_ids), affected


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------

def list_tags(conn) -> list[dict]:
    return repo.tags_all(conn)


def create_tag(conn, name: str) -> dict:
    names = parse_tags(name)
    if len(names) != 1:
        raise ValueError("Enter exactly one tag name")
    return repo.insert_tag(conn, names[0])


def toggle_tag_active(conn, tag_id: int) -> dict:
    row = repo.toggle_tag_active(conn, tag_id)
    if row is None:
        raise ValueError(f"Tag #{tag_id} not found")
    return row


def rename_tag(conn, tag_id: int, name: str) -> str:
    names = parse_tags(name)
    if len(names) != 1:
        raise ValueError("Enter exactly one tag name")
    if repo.rename_tag(conn, tag_id, names[0]) == 0:
        raise ValueError(f"Tag #{tag_id} not found")
    return names[0]


def delete_tag(conn, tag_id: int) -> str:
    name = repo.delete_tag(conn, tag_id)
    if name is None:
        raise ValueError(f"Tag #{tag_id} not found")
    return name


def merge_tags(conn, tag_ids: list[int], target_name: str) -> tuple[int, int]:
    """Returns `(merged_count, entries_affected)` — ported from
    `merge_tags`."""
    if len(tag_ids) < 2:
        raise ValueError("Select at least two tags to merge")
    names = parse_tags(target_name)
    if len(names) != 1:
        raise ValueError("Enter exactly one tag name")
    survivor_id, other_ids = tag_ids[0], tag_ids[1:]
    affected = repo.merge_tags(conn, survivor_id, other_ids, names[0])
    if affected is None:
        raise ValueError(f"Tag #{survivor_id} not found")
    return len(tag_ids), affected

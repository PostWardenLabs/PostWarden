"""Assembly for the analytics module's two families of routes:

- The `/api/*` JSON mirror — thin, one function per `repository.py`
  function of the same name, kept as a real layer (not called directly
  from `router.py`) for the same reason every other module keeps this
  split even where a given route has little logic of its own: it is
  where logic would go if `/api/*` ever grew any (a redaction rule, a
  cache), and it is what every module's own test suite already expects
  to import (`test_service.py` alongside `test_repository.py`/
  `test_router.py`).
- `connect_bi_info`/`pbids_document` — the Settings screen's "Connect
  BI tools" page (`GET /settings/connect-bi`, `GET /settings/connect-bi/
  download.pbids`). There is nowhere else it belongs: it has no module
  of its own, it needs no reference-data lookup any other module owns,
  and its entire content — host/port/database/user plus `BI_OBJECTS`,
  the catalog of what a BI tool can actually query — describes exactly
  the four star-schema views and one SRF this module already owns.
  Folding it in here keeps it out of `main.py`, which stays app factory
  + router mounting only, without inventing a Settings module for two
  routes that have never had anything in common with username/password
  (`modules/auth/`) beyond sharing a `/settings/*` URL prefix.

`postwarden_bi` (SPEC.md decision 14) is a fixed, hardcoded-password
role by design — see `config.py`'s own comment on `postwarden_bi_port`.
Host/port are the only two things that vary per install, so those are
the only two ever read from `Settings`/the request; no credential is
ever sent to the browser.
"""
from ..config import Settings
from . import repository

# What the Connect BI page tells a visitor they can query, not data this
# module fetches. Kept alongside the routes that show it rather than in
# schema.sql, since it's a description of the BI surface for a human,
# not something Postgres itself needs to know.
BI_DB = "postwarden"
BI_USER = "postwarden_bi"
BI_OBJECTS = [
    ("v_dim_account", "Account dimension — hierarchy path, depth, normal side"),
    ("v_fact_lines", "Fact table — one row per journal line, fully denormalized"),
    ("v_dim_date", "Date dimension, 2020–2035"),
    ("v_monthly_activity", "v_fact_lines pre-aggregated to account × month × scenario"),
    ("fn_trial_balance('ACTUAL', '2026-08-31')", "Trial balance at any date, any scenario"),
]


def trial_balance(conn, scenario: str, as_of: str | None) -> list[dict]:
    return repository.trial_balance(conn, scenario, as_of)


def accounts(conn) -> list[dict]:
    return repository.accounts(conn)


def scenarios(conn) -> list[dict]:
    return repository.scenarios(conn)


def entries(conn, scenario: str | None, date_from: str | None, date_to: str | None) -> list[dict]:
    return repository.fact_lines(conn, scenario, date_from, date_to)


def monthly_activity(conn, scenario: str | None) -> list[dict]:
    return repository.monthly_activity(conn, scenario)


def connect_bi_info(hostname: str, settings: Settings) -> dict:
    """The Connect BI page's own render data — host/port/database/user
    plus the `BI_OBJECTS` catalog."""
    return {
        "bi_host": hostname,
        "bi_port": settings.postwarden_bi_port,
        "bi_db": BI_DB,
        "bi_user": BI_USER,
        "bi_objects": BI_OBJECTS,
    }


def pbids_document(hostname: str, settings: Settings) -> dict:
    """A Power BI Data Source (`.pbids`) file's own JSON body —
    double-clicking it in Power BI Desktop opens straight to a
    PostgreSQL connection dialog pre-filled with this instance's own
    host/port/database, nothing to type by hand. No credentials in it:
    Power BI still prompts for the `postwarden_bi` password itself, same
    as connecting manually."""
    return {
        "version": "0.1",
        "connections": [{
            "details": {"protocol": "postgresql", "address": {
                "server": f"{hostname}:{settings.postwarden_bi_port}",
                "database": BI_DB,
            }},
            "mode": "Import",
        }],
    }

"""Central JSON encoding for Decimal and date/datetime — the "documented
gap" REBUILD.md §6 calls out: the legacy app hand-rolled this same fix
twice, per-route (`staging_duplicates_page`'s `groups_json`,
`templates_full()`), both by `str()`-ing every debit/credit before
building the JSON blob, because a plain `json.dumps` has no idea how to
serialize either type. This module makes that the default everywhere
instead of an opt-in per route — but "everywhere" turns out to mean two
genuinely different code paths, both fixed here:

1. **A route that just `return`s a dict/Pydantic model.** FastAPI runs
   that value through `jsonable_encoder` before any `Response` class ever
   sees it. `jsonable_encoder`'s own built-in Decimal handling converts to
   `float` — which silently reintroduces the exact precision-loss risk
   `domain/money.py` and `domain/entry.py` were written to avoid on the
   way *in* (`NUMERIC(18,2)` values that aren't exactly representable in
   binary floating point). `date`/`datetime` are already handled
   correctly here (`.isoformat()`) with no fix needed — verified, not
   assumed; see `test_json.py`. `configure_decimal_encoding()` closes the
   Decimal gap by registering a `str`-based encoder in FastAPI's own
   `ENCODERS_BY_TYPE` registry, once, at app startup — the same string
   form Pydantic models already produce automatically for a `Decimal`
   field (`model_dump(mode="json")`), so response *shape* doesn't change
   based on whether a route happens to declare a `response_model` or not.

2. **A route that explicitly builds `JSONResponse({...})`** — legacy's
   own idiom for the `{"ok": True/False, ...}` action-toast responses
   scattered throughout `app/main.py`, which the ported modules keep
   using rather than inventing a new shape for. `jsonable_encoder` is a
   FastAPI-only convenience that never runs on an already-constructed
   `Response` — Starlette's `JSONResponse.render()` calls plain
   `json.dumps` directly, which raises `TypeError` outright on *either*
   a bare `Decimal` or a bare `date`/`datetime`, no float-downgrade
   fallback available. `JSONResponse` in this module is a drop-in
   replacement (same name, same constructor) whose `render()` supplies a
   `default=` callback handling both.
"""
import json as _json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from starlette.responses import JSONResponse as _StarletteJSONResponse


def encode_json_value(value: Any) -> Any:
    """The `default=` callback for `json.dumps`: called only for a value
    the encoder doesn't already know how to serialize natively.

    Decimal -> str, not float, for the same reason `configure_decimal_
    encoding` below does: this app's money amounts are `NUMERIC(18,2)` in
    Postgres, and a `float` can't represent every two-decimal-place value
    exactly. `datetime` is checked before `date` because `datetime` is a
    subclass of `date` — checking `date` first would match a `datetime`
    too and silently drop its time-of-day component.
    """
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class JSONResponse(_StarletteJSONResponse):
    """Same name and constructor as `fastapi.responses.JSONResponse` — a
    ported route imports this instead (`from postwarden.json import
    JSONResponse`) for the exact same `JSONResponse({"ok": ..., ...})`
    call legacy already makes; nothing else about the call site changes.
    """

    def render(self, content: Any) -> bytes:
        return _json.dumps(
            content,
            ensure_ascii=False,
            allow_nan=False,
            default=encode_json_value,
            separators=(",", ":"),
        ).encode("utf-8")


def configure_decimal_encoding() -> None:
    """Fix `jsonable_encoder`'s Decimal handling, process-wide, once.

    Mutates FastAPI's own `ENCODERS_BY_TYPE` registry — a supported
    extension point (`jsonable_encoder` looks up `type(obj)` in it
    directly), not a private implementation detail. This only needs to
    run once per process; call it from the app factory (`main.py`) before
    the app starts serving. Idempotent, so calling it more than once (as
    tests do) is harmless.
    """
    import fastapi.encoders as fastapi_encoders

    fastapi_encoders.ENCODERS_BY_TYPE[Decimal] = str

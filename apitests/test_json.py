"""Unit tests for postwarden.json — no database.

Covers both response paths described in the module's own docstring: the
implicit dict-return path (FastAPI's jsonable_encoder) and the explicit
JSONResponse(...) path (Starlette's plain json.dumps) — each fails
differently without this module's fix, so each gets its own coverage.
"""
import json
from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.testclient import TestClient

from postwarden.json import JSONResponse, configure_decimal_encoding, encode_json_value


def test_encode_json_value_decimal_becomes_string_not_float():
    # str, not float: 19.99 is not exactly representable in binary
    # floating point, and NUMERIC(18,2) values are the entire reason
    # domain/money.py uses Decimal throughout instead.
    assert encode_json_value(Decimal("19.99")) == "19.99"


def test_encode_json_value_datetime_before_date_keeps_time_of_day():
    # datetime is a subclass of date; checking date first would match a
    # datetime too and silently drop its time component.
    dt = datetime(2026, 1, 31, 13, 45, 0)
    assert encode_json_value(dt) == "2026-01-31T13:45:00"


def test_encode_json_value_plain_date():
    assert encode_json_value(date(2026, 1, 31)) == "2026-01-31"


def test_encode_json_value_raises_on_genuinely_unsupported_type():
    with pytest.raises(TypeError, match="not JSON serializable"):
        encode_json_value(object())


def test_json_response_render_handles_decimal_and_date_together():
    # Starlette's own JSONResponse.render() would raise TypeError on
    # either of these — that's the whole reason this class exists.
    resp = JSONResponse({"ok": True, "amount": Decimal("19.99"), "entry_date": date(2026, 1, 31)})
    body = json.loads(resp.body)
    assert body == {"ok": True, "amount": "19.99", "entry_date": "2026-01-31"}


def test_json_response_still_handles_plain_json_types_normally():
    resp = JSONResponse({"ok": False, "error": "bad input", "count": 3, "extra": None})
    assert json.loads(resp.body) == {"ok": False, "error": "bad input", "count": 3, "extra": None}


def test_configure_decimal_encoding_fixes_jsonable_encoder(monkeypatch):
    import fastapi.encoders as fastapi_encoders

    monkeypatch.setitem(fastapi_encoders.ENCODERS_BY_TYPE, Decimal, lambda d: float(d))
    assert jsonable_encoder({"amount": Decimal("19.99")}) == {"amount": 19.99}

    configure_decimal_encoding()
    assert jsonable_encoder({"amount": Decimal("19.99")}) == {"amount": "19.99"}


def test_end_to_end_implicit_dict_return_uses_string_decimal():
    """A route that just `return`s a dict, through a real TestClient
    request — the path FastAPI's own jsonable_encoder handles."""
    configure_decimal_encoding()
    app = FastAPI(default_response_class=JSONResponse)

    @app.get("/amount")
    def amount() -> dict:
        return {"amount": Decimal("19.99"), "entry_date": date(2026, 1, 31)}

    client = TestClient(app)
    resp = client.get("/amount")
    assert resp.json() == {"amount": "19.99", "entry_date": "2026-01-31"}


def test_end_to_end_explicit_json_response_uses_string_decimal():
    """A route that explicitly builds JSONResponse({...}) — the path
    Starlette's plain json.dumps would otherwise crash on outright, since
    it doesn't go through FastAPI's own Decimal-aware encoder."""
    app = FastAPI()

    @app.post("/action")
    def action() -> JSONResponse:
        return JSONResponse({"ok": True, "amount": Decimal("19.99")})

    client = TestClient(app)
    resp = client.post("/action")
    assert resp.json() == {"ok": True, "amount": "19.99"}

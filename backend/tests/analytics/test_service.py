"""Tests of `analytics.service` — the `/api/*` wrappers are thin
pass-throughs to `repository.py` (already covered directly by
`test_repository.py`), so these focus on what has real logic of its
own: `connect_bi_info`/`pbids_document`, neither of which touch the
database at all."""
from postwarden.analytics import service
from postwarden.config import Settings


def test_connect_bi_info_reflects_host_and_configured_port(monkeypatch):
    monkeypatch.setenv("POSTWARDEN_BI_PORT", "5433")
    info = service.connect_bi_info("ledger.example.com", Settings())
    assert info["bi_host"] == "ledger.example.com"
    assert info["bi_port"] == "5433"
    assert info["bi_db"] == "postwarden"
    assert info["bi_user"] == "postwarden_bi"
    assert ("v_fact_lines", "Fact table — one row per journal line, fully denormalized") in info["bi_objects"]


def test_connect_bi_info_defaults_port_to_5432(monkeypatch):
    monkeypatch.delenv("POSTWARDEN_BI_PORT", raising=False)
    info = service.connect_bi_info("localhost", Settings())
    assert info["bi_port"] == "5432"


def test_pbids_document_embeds_host_port_and_database_no_credentials(monkeypatch):
    monkeypatch.setenv("POSTWARDEN_BI_PORT", "5433")
    doc = service.pbids_document("ledger.example.com", Settings())
    assert doc["connections"][0]["details"]["address"]["server"] == "ledger.example.com:5433"
    assert doc["connections"][0]["details"]["address"]["database"] == "postwarden"
    assert doc["connections"][0]["mode"] == "Import"
    assert "password" not in repr(doc).lower()


def test_api_wrappers_delegate_to_repository(book, conn):
    assert service.accounts(conn) == service.accounts(conn)  # smoke: no crash, stable
    scenarios = {r["code"] for r in service.scenarios(conn)}
    assert {"ACTUAL", "BUDGET2"} <= scenarios
    assert service.trial_balance(conn, "ACTUAL", "2026-02-28")
    assert service.entries(conn, "ACTUAL", None, None)
    assert service.monthly_activity(conn, "ACTUAL")
